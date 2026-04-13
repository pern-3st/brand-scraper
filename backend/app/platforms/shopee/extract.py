"""DOM extraction for Shopee shop-grid pages.

The JS extractor runs against `.shop-search-result-view__item` cards on a
rendered shop page and returns one dict per card containing every field
we promise in ShopeeProductRecord (except `currency` and `scraped_at`,
which are added by the scraper).

Per-field extraction strategy is documented in the JS comment block
inside EXTRACT_JS. See docs/plans/2026-04-10-shopee-spike-notes.md for
the full reasoning behind this DOM-extraction approach and the rejected
alternatives (XHR intercept, click pagination, direct API fetch).
"""
from __future__ import annotations

from urllib.parse import urlparse

from patchright.async_api import Page

GRID_CARD_SELECTOR = ".shop-search-result-view__item"
PAGE_SIZE = 30  # Full grid pages always return exactly 30 cards.


def shop_handle_from_url(shop_url: str) -> str:
    """`https://shopee.sg/levis_singapore` -> `levis_singapore`."""
    path = urlparse(shop_url).path.strip("/")
    if not path:
        raise ValueError(f"could not derive shop handle from {shop_url!r}")
    return path.split("/")[0]


async def extract_grid_items(page: Page) -> list[dict]:
    """Run EXTRACT_JS against the current page and return one dict per card."""
    return await page.evaluate(EXTRACT_JS, GRID_CARD_SELECTOR)


# Verbatim from backend/scripts/shopee_spike.py::EXTRACT_JS. Do not edit —
# every quirk in it (the strikethrough ancestor walk, the $-regex-after-
# whitespace-strip, the susercontent alt-tag filter, the rating leaf
# detection) corresponds to a bug or edge case the spike burned time on.
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
