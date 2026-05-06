"""
Tiny follow-up probe: scroll to bottom, then count rendered product cards in
the DOM so we can compare against the unique XHR auctionIds harvested.

Usage:
    cd backend && uv run python scripts/lazada_dom_probe.py https://www.lazada.sg/shop/lacoste/
"""
import asyncio
import sys
from pathlib import Path

from patchright.async_api import async_playwright

REPO_ROOT = Path(__file__).parent.parent
PROFILE_DIR = REPO_ROOT / "data" / "browser_profiles" / "lazada_sg"

PROBE_JS = r"""
() => {
    // Try several plausible card selectors.
    const candidates = [
        '[data-qa-locator="product-item"]',
        '[data-tracking="product-card"]',
        '.Bm3ON',          // common lazada card hash class
        'div[class*="card"][class*="product" i]',
        'a[href*="/products/pdp-i"]',
    ];
    const out = {};
    for (const sel of candidates) {
        out[sel] = document.querySelectorAll(sel).length;
    }
    // Also bag any anchor that looks like a PDP link with item id
    const pdpLinks = Array.from(document.querySelectorAll('a[href*="/products/pdp-i"]'));
    const ids = new Set();
    for (const a of pdpLinks) {
        const m = a.getAttribute('href').match(/pdp-i(\d+)/);
        if (m) ids.add(m[1]);
    }
    out['unique_pdp_item_ids_in_dom'] = ids.size;
    return out;
}
"""


async def main(url: str):
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        # Aggressive scroll to bottom.
        last = 0
        stable = 0
        for i in range(80):
            await page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            await page.wait_for_timeout(1200)
            h = await page.evaluate("document.documentElement.scrollHeight")
            if h == last:
                stable += 1
                if stable >= 5:
                    break
            else:
                stable = 0
            last = h
        await page.wait_for_timeout(2000)
        result = await page.evaluate(PROBE_JS)
        print("DOM probe result:")
        for k, v in result.items():
            print(f"  {k}: {v}")
        await page.wait_for_timeout(3000)
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
