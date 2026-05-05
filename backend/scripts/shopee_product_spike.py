"""
Shopee product-detail reconnaissance spike ("spike part 2").

Goal: load individual product pages (URLs captured from the shop-grid CSV in
part 1) and dump everything we can observe — XHRs, SSR HTML, a screenshot —
so we can see which detailed fields are available where. No extraction
logic here; this is pure recon, mirroring what shopee_spike.py did before
DOM extraction was settled.

Captures go under:
    backend/scripts/shopee_spike_captures/products/<N>_<itemid>/
        page.html                  # page.content() after load + short settle
        screenshot.png             # full-page screenshot
        meta.json                  # url, title, xhr index, timing
        xhrs/
            <K>_<endpoint>.json        # response body (pretty-printed if JSON)
            <K>_<endpoint>.headers.json # req/resp headers sidecar

Run:
    cd backend && uv run python scripts/shopee_product_spike.py
"""
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from patchright.async_api import async_playwright

REPO_ROOT = Path(__file__).parent.parent
PROFILE_DIR = REPO_ROOT / "data" / "browser_profiles" / "shopee_sg"
CAPTURES_ROOT = REPO_ROOT / "scripts" / "shopee_spike_captures" / "products"

# Three URLs hand-picked from the 2026-04-10 levis_singapore CSV. Intentionally
# random-ish to get a mix of variants/stock states without cherry-picking.
# Plus one high-volume product (#04, 817 sold) added later to verify whether
# monthly_sold ever appears in pdp_get_pc — none of the random three were
# above 5 sold, so they couldn't disprove the field's existence.
PRODUCT_URLS = [
    "https://shopee.sg/Levi's%C2%AE-Men's-Mission-Bay-Crossbody-004C4-0005-i.106712159.41929193489?extraParams=%7B%22display_model_id%22%3A405631763340%2C%22model_selection_logic%22%3A3%7D",
    "https://shopee.sg/Levi's%C2%AE-Women's-Cropped-501-Original%C2%AE-Jeans-A8746-0005-i.106712159.50605205874?extraParams=%7B%22display_model_id%22%3A302359313531%2C%22model_selection_logic%22%3A3%7D",
    "https://shopee.sg/Levi's%C2%AE-Women's-Harlie-Boyfriend-Shirt-001HM-0012-i.106712159.43719714275?extraParams=%7B%22display_model_id%22%3A258913045770%2C%22model_selection_logic%22%3A3%7D",
    "https://shopee.sg/Levi's-505%E2%84%A2-Regular-Fit-Jeans-00505-1550-i.106712159.2018928348?extraParams=%7B%22display_model_id%22%3A3573367657%2C%22model_selection_logic%22%3A3%7D",
]

# Match the shop-grid anchor format: /-i.<shopid>.<itemid>
ITEMID_RE = re.compile(r"-i\.(\d+)\.(\d+)")


def parse_itemid(url: str) -> str:
    m = ITEMID_RE.search(url)
    return m.group(2) if m else "unknown"


def slug_endpoint(url: str) -> str:
    """`/api/v4/pdp/get_pc?itemid=123&shopid=456` -> `pdp_get_pc`"""
    # Strip query string and /api/v4/ prefix, replace / with _
    path = url.split("?", 1)[0]
    path = re.sub(r"^https?://[^/]+", "", path)
    path = re.sub(r"^/api/v\d+/", "", path)
    return path.strip("/").replace("/", "_") or "unknown"


async def capture_one(context, url: str, out_dir: Path, index: int) -> dict:
    """Load one product page, dump everything observable."""
    out_dir.mkdir(parents=True, exist_ok=True)
    xhr_dir = out_dir / "xhrs"
    xhr_dir.mkdir(exist_ok=True)

    page = await context.new_page()
    xhr_log: list[dict] = []
    xhr_counter = {"n": 0}

    async def on_response(response):
        resp_url = response.url
        if "/api/v" not in resp_url:
            return
        try:
            status = response.status
            endpoint = slug_endpoint(resp_url)
            xhr_counter["n"] += 1
            k = xhr_counter["n"]
            stem = f"{k:03d}_{endpoint}"

            # Headers sidecar — request + response headers, status, timing
            headers_file = xhr_dir / f"{stem}.headers.json"
            try:
                req = response.request
                # Capture POST body if any. Try JSON parse for readability;
                # fall back to raw string. post_data is None for GETs.
                post_data_raw = req.post_data
                post_data_parsed: object = None
                if post_data_raw:
                    try:
                        post_data_parsed = json.loads(post_data_raw)
                    except Exception:
                        post_data_parsed = post_data_raw
                headers_obj = {
                    "url": resp_url,
                    "status": status,
                    "method": req.method,
                    "request_headers": await req.all_headers(),
                    "request_post_data": post_data_parsed,
                    "response_headers": await response.all_headers(),
                }
            except Exception as exc:
                headers_obj = {"url": resp_url, "status": status, "error": repr(exc)}
            headers_file.write_text(json.dumps(headers_obj, indent=2, ensure_ascii=False))

            # Body — pretty-print if JSON, else raw bytes
            body_file = xhr_dir / f"{stem}.json"
            try:
                body_bytes = await response.body()
            except Exception as exc:
                body_file.write_text(json.dumps({"_capture_error": repr(exc)}))
                xhr_log.append({"k": k, "url": resp_url, "status": status, "size": 0, "error": repr(exc)})
                return

            size = len(body_bytes)
            try:
                parsed = json.loads(body_bytes)
                body_file.write_text(json.dumps(parsed, indent=2, ensure_ascii=False))
            except Exception:
                # Not JSON — dump raw with a .bin suffix alongside an empty .json
                raw_file = xhr_dir / f"{stem}.bin"
                raw_file.write_bytes(body_bytes)
                body_file.write_text(json.dumps({"_non_json": True, "bytes": size, "raw_file": raw_file.name}))

            xhr_log.append({"k": k, "url": resp_url, "status": status, "size": size, "endpoint": endpoint})
        except Exception as exc:
            xhr_log.append({"url": resp_url, "error": repr(exc)})

    page.on("response", on_response)

    print(f"\n[{index}] -> {url[:100]}...")
    t0 = datetime.now()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        print(f"[{index}] navigation failed: {exc}")
        await page.close()
        return {"url": url, "error": repr(exc)}

    # Let CSR XHRs fire. Product pages commonly load ratings/recommendations
    # after DOMContentLoaded.
    await asyncio.sleep(4)

    # Scroll down once to trigger any lazy-loaded sections (ratings, reviews,
    # "you may also like"). Keep it gentle — one full-viewport jump.
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(3)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)
    except Exception as exc:
        print(f"[{index}] scroll failed: {exc}")

    # Dumps
    try:
        html = await page.content()
        (out_dir / "page.html").write_text(html, encoding="utf-8")
    except Exception as exc:
        print(f"[{index}] page.content failed: {exc}")
        html = ""

    try:
        await page.screenshot(path=str(out_dir / "screenshot.png"), full_page=True)
    except Exception as exc:
        print(f"[{index}] screenshot failed: {exc}")

    try:
        title = await page.title()
    except Exception:
        title = None

    t1 = datetime.now()
    meta = {
        "url": url,
        "title": title,
        "itemid": parse_itemid(url),
        "html_bytes": len(html),
        "xhrs": xhr_log,
        "started_at": t0.isoformat(),
        "ended_at": t1.isoformat(),
        "duration_s": (t1 - t0).total_seconds(),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    print(
        f"[{index}] done in {meta['duration_s']:.1f}s — "
        f"html={len(html)}B xhrs={len(xhr_log)} title={title!r}"
    )
    await page.close()
    return meta


async def main() -> None:
    CAPTURES_ROOT.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 900},
        )

        summaries = []
        for i, url in enumerate(PRODUCT_URLS, start=1):
            itemid = parse_itemid(url)
            out_dir = CAPTURES_ROOT / f"{i:02d}_{itemid}"
            summary = await capture_one(context, url, out_dir, i)
            summaries.append(summary)
            # Polite delay between product hits — first line of defense
            # against the higher-volume access pattern.
            if i < len(PRODUCT_URLS):
                await asyncio.sleep(2)

        await context.close()

    (CAPTURES_ROOT / "run_summary.json").write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False)
    )
    print(f"\n[done] captures -> {CAPTURES_ROOT}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[interrupted]")
        sys.exit(130)
