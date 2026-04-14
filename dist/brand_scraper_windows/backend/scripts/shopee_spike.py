"""
Shopee shop catalog scraper.

Promoted from the 2026-04-10 spike. Pagination is nav-based: hard-navigate to
`?page=N&sortBy=pop&tab=0` for each page and read all 30 grid cards directly
from the SSR DOM via a single page.evaluate. Termination is "zero new
itemids on a navigation". The XHR-capture and click-pagination paths were
both rejected during the spike — see docs/plans/2026-04-10-shopee-spike-notes.md
for the full reasoning.

The persistent profile at data/browser_profiles/shopee_sg/ carries cookies
across runs. First run requires a manual login in the launched Chrome window.
Run with `headless=False` because Shopee detects headless and the login flow
needs a real window.

Output: backend/data/shopee/<handle>/<YYYY-MM-DDTHH-MM-SS>.csv

Schema (DOM-extractable; fields not in this list — likes, monthly sold,
category names, shop_id — were dropped because they're either not rendered
in the card markup, only available for the 30 items the SSR XHR happens to
return on page 1, or constant across the whole run):

    item_id, product_name, product_url, image_url,
    price, mrp, currency, discount_pct,
    rating_star, historical_sold_count, is_sold_out

`mrp` is the original (pre-discount) list price. Resolution order:
  1. Strikethrough $-text in the card's price block (preferred — exact value)
  2. Computed from price + discount_pct (when only the -N% badge renders)
  3. Equal to price (when there's no discount at all)

Usage:
    cd backend && uv run python scripts/shopee_spike.py https://shopee.sg/levis_singapore
"""
import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from patchright.async_api import async_playwright

REPO_ROOT = Path(__file__).parent.parent
PROFILE_DIR = REPO_ROOT / "data" / "browser_profiles" / "shopee_sg"
OUTPUT_ROOT = REPO_ROOT / "data" / "shopee"

# Confirmed on 2026-04-10: matches exactly 30 grid cards per page on a full page.
GRID_CARD_SELECTOR = ".shop-search-result-view__item"
PAGE_SIZE = 30

CSV_FIELDS = [
    "item_id",
    "product_name",
    "product_url",
    "image_url",
    "price",
    "mrp",
    "currency",
    "discount_pct",
    "rating_star",
    "historical_sold_count",
    "is_sold_out",
]


# JS extractor. One round-trip per page pulls all 30 cards' fields out of
# the SSR DOM. Strategies per field:
#
#   item_id, shop_id   parsed from the product anchor's href via -i.<shop>.<item>
#   product_url        anchor href made absolute against window.location.origin
#   product_name       img.alt of the first non-decoration susercontent.com image,
#                      fallback to .line-clamp-2 innerText
#   image_url          src of the same img
#   price              [aria-label*="price"] container's innerText, $-regex after
#                      stripping whitespace (Shopee splits $ and digits across
#                      sibling spans, so a literal newline lives between them)
#   mrp                three-tier resolution:
#                      (1) any $-amount element where the element OR an ancestor
#                          (within the card) has computed text-decoration
#                          line-through. Catches `<del>`, inline style, and
#                          class-based strikethroughs even when the rendered
#                          $-digits live in a child span (text-decoration's
#                          computed style does NOT cascade to descendants in
#                          getComputedStyle, so we must walk up).
#                      (2) computed from price * 100 / (100 - discount_pct)
#                          when the card only renders a "-N%" badge with no
#                          visible original price (common on SG shop grids).
#                      (3) equal to price when there's no discount at all.
#   discount_pct       regex /-(\d+)\s*%/ on the card's full innerText. Discount
#                      tag is the only "-N%" pattern in a card.
#   rating_star        first leaf element whose textContent matches /^\d\.\d/
#                      (decimal at start, possibly trailing " Shop Rating").
#                      Sold counts are integer-prefixed ("33 sold"), prices are
#                      $-prefixed, so a leading bare decimal is unambiguously
#                      the rating.
#   historical_sold_count  regex /(\d+(?:[.,]\d+)?)\s*([kKmM]?)\+?\s*sold/ on
#                      full innerText. Handles "33 sold", "1.2k sold", "100+ sold".
#   is_sold_out        /\bsold\s*out\b/i on full innerText — the JSON's
#                      mask_text "Sold Out" renders as overlay text on sold-out
#                      cards.
EXTRACT_JS = r"""
(sel) => {
    const cards = document.querySelectorAll(sel);
    const results = [];
    for (const card of cards) {
        const row = {
            item_id: null,
            product_name: null,
            product_url: null,
            image_url: null,
            price: null,
            mrp: null,
            discount_pct: null,
            rating_star: null,
            historical_sold_count: null,
            is_sold_out: false,
        };

        // --- IDs + product URL from the anchor ---
        const anchor = card.querySelector('a[href*="-i."]');
        if (!anchor) continue;
        const href = anchor.getAttribute('href') || '';
        const idMatch = href.match(/-i\.(\d+)\.(\d+)/);
        if (!idMatch) continue;
        row.item_id = parseInt(idMatch[2], 10);
        try {
            row.product_url = new URL(href, window.location.origin).toString();
        } catch (_) {
            row.product_url = href;
        }

        // --- Name + image from the first non-decoration susercontent img ---
        for (const img of card.querySelectorAll('img')) {
            const src = img.getAttribute('src') || '';
            const alt = img.getAttribute('alt') || '';
            if (!src.includes('susercontent.com/file/')) continue;
            if (alt === 'flag-label' || alt === 'custom-overlay') continue;
            row.image_url = src;
            if (alt) row.product_name = alt;
            break;
        }
        if (!row.product_name) {
            const titleEl = card.querySelector('.line-clamp-2');
            if (titleEl) row.product_name = (titleEl.innerText || '').trim() || null;
        }

        // --- Price (current/discounted) ---
        let priceText = null;
        const priceMark = card.querySelector('[aria-label*="price" i]');
        if (priceMark) {
            const container = priceMark.parentElement || priceMark;
            priceText = (container.innerText || '').trim();
        }
        if (priceText) {
            const stripped = priceText.replace(/\s+/g, '');
            const m = stripped.match(/\$([\d.,]+)/);
            if (m) row.price = parseFloat(m[1].replace(/,/g, ''));
        }

        // --- MRP via computed text-decoration: line-through ---
        // text-decoration's computed style does NOT cascade to descendants in
        // getComputedStyle results. If Shopee renders the strikethrough as
        // `<del><span>$</span><span>64.90</span></del>`, the SPAN children
        // report `text-decoration-line: none` while the DEL parent reports
        // `line-through`. So for each $-amount leaf, we walk up to the card
        // boundary checking for line-through anywhere in the ancestor chain.
        const isStrikethrough = (el) => {
            let cur = el;
            while (cur && cur !== card) {
                const s = window.getComputedStyle(cur);
                const td = (s.textDecorationLine || '') + ' ' + (s.textDecoration || '');
                if (td.includes('line-through')) return true;
                cur = cur.parentElement;
            }
            return false;
        };
        for (const el of card.querySelectorAll('*')) {
            const stripped = (el.textContent || '').replace(/\s+/g, '');
            if (!/^\$[\d.,]/.test(stripped)) continue;
            // Skip parent elements whose textContent merges multiple
            // $-amounts (e.g. "$54.90$64.90"). We want the smallest container
            // wrapping a single $-amount, so we can attribute strikethrough
            // styling correctly.
            let hasMoneyChild = false;
            for (const child of el.children) {
                const ct = (child.textContent || '').replace(/\s+/g, '');
                if (/^\$[\d.,]/.test(ct)) { hasMoneyChild = true; break; }
            }
            if (hasMoneyChild) continue;
            if (!isStrikethrough(el)) continue;
            const m = stripped.match(/\$([\d.,]+)/);
            if (m) {
                row.mrp = parseFloat(m[1].replace(/,/g, ''));
                break;
            }
        }

        // --- Full-text scans ---
        const fullText = card.innerText || '';

        // discount_pct
        const discMatch = fullText.match(/-(\d+)\s*%/);
        if (discMatch) row.discount_pct = parseInt(discMatch[1], 10);

        // historical_sold_count
        const soldMatch = fullText.match(/(\d+(?:[.,]\d+)?)\s*([kKmM]?)\+?\s*sold/);
        if (soldMatch) {
            let n = parseFloat(soldMatch[1].replace(',', '.'));
            const suffix = (soldMatch[2] || '').toLowerCase();
            if (suffix === 'k') n *= 1000;
            else if (suffix === 'm') n *= 1000000;
            row.historical_sold_count = Math.round(n);
        }

        // is_sold_out — overlay text "Sold Out" rendered on sold-out cards
        row.is_sold_out = /\bsold\s*out\b/i.test(fullText);

        // mrp fallback: when the card only renders the "-N%" badge and no
        // visible original price, compute mrp from price + discount_pct.
        // For items with no discount (no badge), mrp == price.
        if (row.mrp === null && row.price !== null) {
            if (row.discount_pct && row.discount_pct > 0 && row.discount_pct < 100) {
                row.mrp = Math.round(row.price * 100 / (100 - row.discount_pct) * 100) / 100;
            } else {
                row.mrp = row.price;
            }
        }

        // rating_star — first leaf element whose textContent starts with a
        // decimal like "4.7" or "4.9 Shop Rating". Skip elements that have
        // child elements (we want the leaf where the text actually lives).
        for (const el of card.querySelectorAll('*')) {
            if (el.children.length > 0) continue;
            const t = (el.textContent || '').trim();
            const m = t.match(/^(\d\.\d)(?:\s|$)/);
            if (!m) continue;
            const v = parseFloat(m[1]);
            if (v < 0 || v > 5) continue;
            row.rating_star = v;
            break;
        }

        results.push(row);
    }
    return results;
}
"""


def shop_handle_from_url(shop_url: str) -> str:
    """`https://shopee.sg/levis_singapore` -> `levis_singapore`."""
    path = urlparse(shop_url).path.strip("/")
    if not path:
        raise ValueError(f"could not derive shop handle from {shop_url!r}")
    return path.split("/")[0]


def serialize_row(row: dict) -> dict:
    """Convert JS-side values to CSV-friendly strings.

    - bool -> "true"/"false" (cleaner than Python's "True"/"False")
    - None -> "" (DictWriter default)
    - everything else passes through
    """
    out = {}
    for k in CSV_FIELDS:
        v = row.get(k)
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif v is None:
            out[k] = ""
        else:
            out[k] = v
    return out


async def scrape_shop(shop_url: str) -> int:
    handle = shop_handle_from_url(shop_url)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_dir = OUTPUT_ROOT / handle
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{timestamp}.csv"

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    cumulative: set[int] = set()
    rows_written = 0

    print(f"[init] shop={shop_url}")
    print(f"[init] output={out_file}")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 900},
        )
        page = await context.new_page()

        with out_file.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            writer.writeheader()
            fh.flush()

            page_idx = 0
            while True:
                page_idx += 1
                target = (
                    shop_url
                    if page_idx == 1
                    else f"{shop_url}?page={page_idx}&sortBy=pop&tab=0"
                )
                print(f"\n[page {page_idx}] -> {target}")

                try:
                    await page.goto(target, wait_until="domcontentloaded")
                except Exception as exc:
                    print(f"[page {page_idx}] navigation failed: {exc} — stopping")
                    break

                # Cards usually exist at domcontentloaded (SSR) but give them
                # a beat to settle in case the shop is slow.
                try:
                    await page.wait_for_selector(GRID_CARD_SELECTOR, timeout=10000)
                except Exception:
                    if page_idx == 1:
                        print(
                            "[error] page 1 has no grid cards. Likely causes: "
                            "profile expired (re-login in the open window), "
                            "Shopee changed the card selector, or the shop URL "
                            "is wrong. Aborting."
                        )
                        await context.close()
                        sys.exit(1)
                    print(
                        f"[page {page_idx}] no grid cards within 10s — assuming end of catalog"
                    )
                    break

                items = await page.evaluate(EXTRACT_JS, GRID_CARD_SELECTOR)
                new_items = [
                    it for it in items if it.get("item_id") not in cumulative
                ]
                for it in new_items:
                    it["currency"] = "SGD"
                    writer.writerow(serialize_row(it))
                    cumulative.add(it["item_id"])
                fh.flush()
                rows_written += len(new_items)

                # Per-page missing-field counts so we can spot fields that
                # never extract and need adjusting.
                missing = {
                    k: sum(1 for it in items if it.get(k) in (None, ""))
                    for k in CSV_FIELDS
                    if k != "currency"
                }
                missing_summary = {
                    k: v for k, v in missing.items() if v
                } or "none"
                print(
                    f"[page {page_idx}] extracted={len(items)} new={len(new_items)} "
                    f"cumulative={len(cumulative)} missing={missing_summary}"
                )

                if not new_items:
                    print(f"[page {page_idx}] zero new items — catalog exhausted")
                    break

        await context.close()

    print(f"\n[done] {rows_written} rows -> {out_file}")
    return rows_written


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: shopee_spike.py <shopee shop url>")
        sys.exit(1)
    try:
        asyncio.run(scrape_shop(sys.argv[1]))
    except KeyboardInterrupt:
        print("\n[interrupted]")
        sys.exit(130)


if __name__ == "__main__":
    main()
