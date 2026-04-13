"""
Throwaway probe v2: answer the three open questions after the first spike run
where the top mini-page-controller clicks landed (counter walked 1/23 -> 4/23)
but fired NO new search_items XHRs:

  Q1. Does clicking the top next-btn fire ANY /api/v4/* call?
  Q2. Is there another paginator (the "bottom" numbered one with '...') that
      wasn't in the initial DOM because it lazy-renders on scroll?
  Q3. If yes to Q2, what are its real class names / selectors?

Mechanics:
  - Tag every /api/v4/ response with the current phase (load / scroll / click).
  - After initial load, step-scroll to the bottom so IntersectionObserver-
    driven components get a chance to render.
  - Re-probe the DOM with broader class patterns + a structural heuristic
    (containers with 5-15 children that include numeric text — the shape of
    a numbered paginator).
  - Click the top next-btn once and watch XHRs for 5s.
  - Dump everything to a single text report for pasting back.

Usage:
    cd backend && uv run python scripts/shopee_probe_pagination_v2.py https://shopee.sg/levis_singapore
"""
import asyncio
import sys
from pathlib import Path

from patchright.async_api import async_playwright

REPO_ROOT = Path(__file__).parent.parent
PROFILE_DIR = REPO_ROOT / "data" / "browser_profiles" / "shopee_sg"
REPORT_FILE = Path(__file__).parent / "shopee_spike_captures" / "paginator_probe_v2.txt"

BROAD_PROBE_JS = r"""
() => {
    const out = [];
    const push = (title, els) => {
        if (!els || !els.length) {
            out.push(`--- ${title} ---`);
            out.push('NO MATCHES');
            out.push('');
            return;
        }
        out.push(`--- ${title} (${els.length} match) ---`);
        els.slice(0, 8).forEach((el, i) => {
            const cls = (el.className && el.className.toString) ? el.className.toString() : '';
            out.push(`[${i}] <${el.tagName.toLowerCase()} class="${cls}">`);
            const html = el.outerHTML;
            out.push(html.length > 2500 ? html.slice(0, 2500) + '\n...[truncated]' : html);
            out.push('');
        });
    };

    push('A. class contains "paginator"',
        Array.from(document.querySelectorAll('[class*="paginator"]')));
    push('B. class contains "page-controller" (singular or plural)',
        Array.from(document.querySelectorAll('[class*="page-controller"]')));
    push('C. class contains "page-controls"',
        Array.from(document.querySelectorAll('[class*="page-controls"]')));
    push('D. class contains "pagination"',
        Array.from(document.querySelectorAll('[class*="pagination"]')));
    push('E. class contains "shopee-page"',
        Array.from(document.querySelectorAll('[class*="shopee-page"]')));

    // Structural heuristic: containers with 5-15 direct children where the
    // children include numeric text — the shape of a numbered paginator
    // (1, 2, 3, 4, 5, ..., next).
    const structural = [];
    document.querySelectorAll('div, ul, nav, section').forEach(c => {
        const kids = Array.from(c.children);
        if (kids.length < 5 || kids.length > 15) return;
        const numericKids = kids.filter(k => /^\s*\d+\s*$/.test(k.textContent || ''));
        // At least 3 purely-numeric children = looks like numbered pagination
        if (numericKids.length >= 3) structural.push(c);
    });
    push('F. STRUCTURAL: containers with 5-15 children, >=3 purely-numeric',
        structural);

    // Text-based: buttons/anchors whose text is just "Next" / ">" / "›" / "Previous" / "<" / "‹"
    const textMatches = Array.from(document.querySelectorAll('button, a, span'))
        .filter(el => /^\s*(next|previous|prev|›|‹|>|<)\s*$/i.test(el.textContent || ''));
    push('G. text is Next/Prev/arrow symbol',
        textMatches);

    // Any button containing an SVG with "arrow" in the class (Shopee's icon convention)
    const svgArrows = Array.from(document.querySelectorAll('button'))
        .filter(b => b.querySelector('svg[class*="arrow"]'));
    push('H. <button> containing <svg class*="arrow">',
        svgArrows);

    return out.join('\n');
}
"""


async def main(shop_url: str) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    search_items_arrived = asyncio.Event()
    xhr_log: list[dict] = []
    current_phase = {"value": "load"}

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 900},
        )
        page = await context.new_page()

        async def on_response(response):
            url = response.url
            if "/api/v4/" not in url:
                return
            path = url.split("?", 1)[0].split("/api/v4/", 1)[-1]
            query = url.split("?", 1)[1] if "?" in url else ""
            xhr_log.append({
                "phase": current_phase["value"],
                "status": response.status,
                "path": path,
                "query": query[:250],
            })
            if "/api/v4/shop/search_items" in url and not search_items_arrived.is_set():
                search_items_arrived.set()

        page.on("response", on_response)

        print(f"[nav] {shop_url}")
        await page.goto(shop_url, wait_until="domcontentloaded")

        print("[wait] initial search_items (up to 20s)...")
        try:
            await asyncio.wait_for(search_items_arrived.wait(), timeout=20)
            print("[wait] got it")
        except asyncio.TimeoutError:
            print("[wait] timed out — continuing anyway")

        # Let the load phase drain a beat
        await asyncio.sleep(1.5)
        load_count = len(xhr_log)
        print(f"[load] {load_count} /api/v4/ calls captured")

        # Phase: scroll to bottom in steps
        current_phase["value"] = "scroll"
        print("\n[scroll] stepping to bottom of page...")
        steps = 8
        for i in range(1, steps + 1):
            pct = i / steps
            await page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {pct})")
            await asyncio.sleep(1.0)
        # Give lazy renders a final beat
        await asyncio.sleep(1.5)
        scroll_count = len(xhr_log) - load_count
        print(f"[scroll] {scroll_count} /api/v4/ calls captured during scroll")

        # Phase: broader DOM probe now that we've scrolled
        print("\n[probe] broad DOM sweep for pagination candidates...")
        probe_out = await page.evaluate(BROAD_PROBE_JS)

        # Phase: click the top next-btn
        current_phase["value"] = "click"
        print("\n[click] clicking top next-btn; watching 5s for XHRs...")
        pre_click_count = len(xhr_log)
        click_note = ""
        try:
            next_btn = page.locator("button.shopee-mini-page-controller__next-btn")
            if await next_btn.count() == 0:
                click_note = "next-btn not found in DOM"
            elif await next_btn.is_disabled():
                click_note = "next-btn is disabled"
            else:
                # Scroll it back into view first; we just scrolled to the bottom
                await next_btn.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                await next_btn.click()
                click_note = "clicked"
        except Exception as exc:
            click_note = f"click raised: {exc}"
        print(f"[click] {click_note}")
        await asyncio.sleep(5)
        click_count = len(xhr_log) - pre_click_count
        print(f"[click] {click_count} /api/v4/ calls in 5s after click")

        # Read live paginator state after click for sanity
        try:
            state_text = (await page.locator(".shopee-mini-page-controller__state").inner_text()).strip()
        except Exception:
            state_text = "<not found>"

        # Write the report
        lines = [
            "=" * 72,
            "SHOPEE PAGINATION PROBE v2",
            "=" * 72,
            f"URL: {shop_url}",
            f"Top paginator state after click: {state_text}",
            f"Click outcome: {click_note}",
            "",
            "COUNTS BY PHASE",
            "-" * 72,
            f"  load:   {load_count}",
            f"  scroll: {scroll_count}",
            f"  click:  {click_count}",
            "",
            "ALL /api/v4/ CALLS",
            "-" * 72,
        ]
        for e in xhr_log:
            lines.append(f"[{e['phase']:6}] {e['status']} /api/v4/{e['path']}")
            if e["query"]:
                lines.append(f"           ?{e['query']}")
        lines.append("")
        lines.append("=" * 72)
        lines.append("DOM PROBE (after scroll-to-bottom)")
        lines.append("=" * 72)
        lines.append("")
        lines.append(probe_out)

        REPORT_FILE.write_text("\n".join(lines))
        print(f"\n[report] {REPORT_FILE}")
        print(f"[report] {REPORT_FILE.stat().st_size} bytes")

        print("\n[idle] browser stays open 120s for manual inspection (Ctrl-C to exit)")
        try:
            await asyncio.sleep(120)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await context.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: shopee_probe_pagination_v2.py <shopee shop url>")
        sys.exit(1)
    try:
        asyncio.run(main(sys.argv[1]))
    except KeyboardInterrupt:
        pass
