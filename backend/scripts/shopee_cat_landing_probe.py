"""Probe whether https://shopee.sg/-cat.{cid} pages contain server-rendered
category names we can scrape — both via <title>, h1 breadcrumb, and any
embedded JSON state.
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.platforms.shopee._session import launch_persistent_context

LEAFS = [100011, 100017, 100009, 100016, 100533]
OUT_DIR = Path(__file__).resolve().parents[1] / "scripts" / "shopee_spike_captures" / "category_tree"


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    async with launch_persistent_context() as (_p, context):
        page = await context.new_page()
        all_api = []

        async def on_response(resp):
            if "/api/v4/" not in resp.url and "/api/v2/" not in resp.url:
                return
            try:
                body = await resp.body()
                data = json.loads(body)
            except Exception:
                return
            all_api.append((resp.url, data))

        page.on("response", on_response)

        # Warm up to avoid bot wall on first cat-landing
        await page.goto("https://shopee.sg/", wait_until="domcontentloaded")
        await asyncio.sleep(5.0)

        for cid in LEAFS:
            all_api.clear()
            url = f"https://shopee.sg/-cat.{cid}"
            print(f"\n=== catid {cid} ===")
            print(f"[nav] {url}")
            try:
                await page.goto(url, wait_until="domcontentloaded")
            except Exception as exc:
                print(f"  nav failed: {exc}")
                continue
            await asyncio.sleep(5.0)
            title = await page.title()
            h1 = await page.evaluate("() => { const h = document.querySelector('h1'); return h ? h.innerText : null; }")
            # try common breadcrumb selectors
            breadcrumb = await page.evaluate(
                """() => {
                  const sels = ['.shopee-breadcrumb', 'nav[aria-label*=breadcrumb i]', '.breadcrumb', '[class*=Breadcrumb]'];
                  for (const s of sels) {
                    const el = document.querySelector(s);
                    if (el) return { sel: s, text: el.innerText };
                  }
                  return null;
                }"""
            )
            ld = await page.evaluate(
                """() => Array.from(document.querySelectorAll('script[type=\"application/ld+json\"]')).map(s => s.textContent)"""
            )
            # Inspect full HTML for any catid → name pattern
            html = await page.content()
            name_in_html = None
            m = re.search(rf'"catid"\s*:\s*{cid}\s*,\s*"display_name"\s*:\s*"([^"]+)"', html)
            if m:
                name_in_html = m.group(1)
            else:
                m = re.search(rf'"display_name"\s*:\s*"([^"]+)"\s*,\s*"catid"\s*:\s*{cid}\b', html)
                if m:
                    name_in_html = m.group(1)
            print(f"  title: {title!r}")
            print(f"  h1: {h1!r}")
            print(f"  breadcrumb: {breadcrumb}")
            print(f"  ld+json blocks: {len(ld) if ld else 0}")
            if ld:
                for blk in ld[:2]:
                    print(f"    [ld] {blk[:200]}")
            print(f"  display_name regex hit: {name_in_html!r}")
            print(f"  /api/v4/* fired during this nav: {len(all_api)}")
            for u, _ in all_api[:8]:
                print(f"    - {u.split('shopee.sg')[1][:120]}")

            (OUT_DIR / f"catlanding_{cid}.html").write_text(html)


if __name__ == "__main__":
    asyncio.run(main())
