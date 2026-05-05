"""Probe /api/v4/search/get_fe_category_detail with both the 6-digit
global catids returned by rcmd_items and the 8-digit homepage catids
to see which space (if either) it accepts.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.platforms.shopee._session import launch_persistent_context

OUT_DIR = Path(__file__).resolve().parents[1] / "scripts" / "shopee_spike_captures" / "category_tree"

# 6-digit global catids from Levi's rcmd_items
SIX_DIGIT = [100011, 100017, 100009, 100016, 100533, 100047, 100050, 100099, 100230, 100242]
# 8-digit SG-localized catids from homepage_category_list
EIGHT_DIGIT = [11012819, 11012963, 11013350, 11000001, 11013247]


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    async with launch_persistent_context() as (_p, context):
        page = await context.new_page()
        # Warm up by visiting the homepage so referer + cookies are real.
        print("[nav] https://shopee.sg/")
        await page.goto("https://shopee.sg/", wait_until="domcontentloaded")
        await asyncio.sleep(5.0)

        async def try_url(label: str, path: str) -> None:
            print(f"\n[{label}] GET {path}")
            try:
                result = await page.evaluate(
                    """async (p) => {
                      const r = await fetch(p, { credentials: 'include',
                        headers: { 'x-api-source': 'pc', 'x-shopee-language': 'en' } });
                      const t = await r.text();
                      return { status: r.status, body: t };
                    }""",
                    path,
                )
                status = result.get("status")
                body = result.get("body") or ""
                print(f"  status={status}, body_len={len(body)}")
                if status == 200:
                    try:
                        data = json.loads(body)
                        print(f"  top keys: {list(data.keys())[:8]}")
                        if "data" in data:
                            d = data["data"]
                            if isinstance(d, dict):
                                print(f"  data keys: {list(d.keys())[:12]}")
                            print(f"  body[:500]={json.dumps(d, ensure_ascii=False)[:500]}")
                        stem = label.replace("/", "_").replace("?", "_").replace("=", "_").replace(",", "_")[:80]
                        (OUT_DIR / f"feprobe_{stem}.json").write_text(body)
                    except Exception as exc:
                        print(f"  json parse failed: {exc}")
                        print(f"  body[:200]={body[:200]!r}")
                else:
                    print(f"  body[:200]={body[:200]!r}")
            except Exception as exc:
                print(f"  [error] {type(exc).__name__}: {exc}")

        # Path variants × ID space
        for cid in [100011, 100017]:
            await try_url(f"6digit-{cid}", f"/api/v4/search/get_fe_category_detail?catids={cid}")
        await try_url("6digit-list", f"/api/v4/search/get_fe_category_detail?catids={','.join(map(str, SIX_DIGIT))}")
        for cid in [11012819, 11012963]:
            await try_url(f"8digit-{cid}", f"/api/v4/search/get_fe_category_detail?catids={cid}")
        # Also try alternative separators / parameter names
        await try_url("alt-catid-single", f"/api/v4/search/get_fe_category_detail?catid=100011")
        await try_url("alt-catids-array", "/api/v4/search/get_fe_category_detail?catids[]=100011&catids[]=100017")


if __name__ == "__main__":
    asyncio.run(main())
