"""
Throwaway probe: open a shopee.sg shop page with the existing persistent
profile, wait for the grid to render, and dump every candidate pagination
container to disk so we can see the real class names / structure.

Paste the contents of the output file back into the spike conversation so
the selectors in shopee_spike.py can be locked in.

Usage:
    cd backend && uv run python scripts/shopee_probe_pagination.py https://shopee.sg/levis_singapore
"""
import asyncio
import sys
from pathlib import Path

from patchright.async_api import async_playwright

REPO_ROOT = Path(__file__).parent.parent
PROFILE_DIR = REPO_ROOT / "data" / "browser_profiles" / "shopee_sg"
OUT_FILE = Path(__file__).parent / "shopee_spike_captures" / "paginator_probe.html"

PROBE_JS = r"""
() => {
    const sections = [];
    const pushSection = (title, elements) => {
        if (!elements.length) {
            sections.push(`<!-- === ${title}: NO MATCHES === -->`);
            return;
        }
        sections.push(`<!-- === ${title}: ${elements.length} match(es) === -->`);
        elements.forEach((el, i) => {
            const cls = el.className && el.className.toString ? el.className.toString() : '';
            sections.push(`<!-- [${i}] <${el.tagName.toLowerCase()} class="${cls}"> -->`);
            sections.push(el.outerHTML);
            sections.push('');
        });
    };

    pushSection(
        'A. class contains "page-controls"',
        Array.from(document.querySelectorAll('[class*="page-controls"]'))
    );
    pushSection(
        'B. class contains "pagination"',
        Array.from(document.querySelectorAll('[class*="pagination"]'))
    );
    pushSection(
        'C. class contains "shopee-mini-page"',
        Array.from(document.querySelectorAll('[class*="shopee-mini-page"]'))
    );
    pushSection(
        'D. class contains "page-navigator"',
        Array.from(document.querySelectorAll('[class*="page-navigator"]'))
    );

    // Find elements whose direct text matches "N/M" — that's the top paginator's
    // "1/23" indicator. Then lift to a nearby ancestor so we see the surrounding
    // arrow buttons too.
    const numPattern = /^\s*\d+\s*\/\s*\d+\s*$/;
    const candidates = Array.from(document.querySelectorAll('div, span'));
    const numHits = candidates.filter(el => {
        const direct = Array.from(el.childNodes)
            .filter(n => n.nodeType === Node.TEXT_NODE)
            .map(n => n.textContent || '')
            .join('');
        return numPattern.test(direct);
    });
    // Lift two ancestors up so we capture the arrow siblings
    const liftedNumHits = numHits.map(el => {
        let cur = el;
        for (let i = 0; i < 2 && cur.parentElement; i++) cur = cur.parentElement;
        return cur;
    });
    pushSection('E. text "N/M" (top paginator indicator, lifted 2 ancestors)', liftedNumHits);

    // Broader safety net: any <button> inside something that also contains an
    // element with text matching "N/M" — catches the top paginator even if
    // class names are unfamiliar.
    pushSection(
        'F. all <button> elements inside a container with "N/M" text',
        liftedNumHits.flatMap(el => Array.from(el.querySelectorAll('button')))
    );

    return sections.join('\n');
}
"""


async def main(shop_url: str) -> None:
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    search_items_arrived = asyncio.Event()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 900},
        )
        page = await context.new_page()

        async def on_response(response):
            if (
                "/api/v4/shop/search_items" in response.url
                and response.status == 200
                and not search_items_arrived.is_set()
            ):
                search_items_arrived.set()

        page.on("response", on_response)

        print(f"[nav] {shop_url}")
        await page.goto(shop_url, wait_until="domcontentloaded")

        print("[wait] waiting for initial search_items XHR (up to 20s)...")
        try:
            await asyncio.wait_for(search_items_arrived.wait(), timeout=20)
            print("[wait] got search_items — giving DOM 2s to render the paginator")
            await asyncio.sleep(2)
        except asyncio.TimeoutError:
            print("[wait] timed out; probing whatever is rendered anyway")

        print("[probe] collecting paginator HTML...")
        html = await page.evaluate(PROBE_JS)
        OUT_FILE.write_text(html)
        print(f"[probe] wrote {len(html)} chars -> {OUT_FILE}")

        print("\n[idle] browser stays open for 120s so you can cross-check in DevTools")
        print("[idle]   (Ctrl-C to exit immediately)")
        try:
            await asyncio.sleep(120)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await context.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: shopee_probe_pagination.py <shopee shop url>")
        sys.exit(1)
    try:
        asyncio.run(main(sys.argv[1]))
    except KeyboardInterrupt:
        pass
