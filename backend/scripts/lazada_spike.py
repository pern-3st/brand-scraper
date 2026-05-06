"""
Lazada shop catalog spike — capture-only.

Goal: open a Lazada brand shop page (e.g. https://www.lazada.sg/shop/lacoste/),
auto-scroll to trigger the infinite-scroll pagination, dump every JSON-ish
response from Lazada-owned hosts to disk, and print a one-line summary per
response so we can eyeball which endpoint is the catalog feed.

No extraction logic yet — this is the equivalent of the early shopee_spike
captures. Read the dumped files in backend/scripts/lazada_spike_captures/
afterwards to figure out the pagination/schema story.

First run will likely require a manual interaction (geo prompt, cookie
banner, possibly a login). The persistent profile at
backend/data/browser_profiles/lazada_sg/ carries cookies across runs.

Usage:
    cd backend && uv run python scripts/lazada_spike.py https://www.lazada.sg/shop/lacoste/
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from patchright.async_api import async_playwright

REPO_ROOT = Path(__file__).parent.parent
PROFILE_DIR = REPO_ROOT / "data" / "browser_profiles" / "lazada_sg"
CAPTURE_DIR = Path(__file__).parent / "lazada_spike_captures"

# Match anything Lazada/Alibaba-stack so we don't miss the catalog endpoint.
# The infinite-scroll feed on Lazada storefronts typically lives on
# acs.lazada.com (mtop) or lazada.sg/api/..., but we cast wide.
HOST_PATTERN = re.compile(r"(lazada|alicdn|aliexpress|mtop)", re.I)

# Auto-scroll tunables. Lazada's "load more" trigger is almost certainly
# observer-on-sentinel — a hard jump-to-bottom only fires it once because
# the sentinel ends up above the viewport on the next jump and never
# re-enters. So we step down in small increments to mimic a human scroll.
SCROLL_STEP_PX = 700           # how far to scroll each tick
SCROLL_TICK_MS = 400           # pause between ticks
BOTTOM_DWELL_MS = 1800         # extra pause after a tick that sat at bottom
MAX_TICKS = 600                # hard cap so we don't loop forever
STABLE_HEIGHT_TICKS = 12       # ticks at unchanged bottom before we stop


def slug_for(url: str) -> str:
    """Make a filesystem-friendly slug from a URL: host + last 2 path segments."""
    p = urlparse(url)
    host = (p.hostname or "unknown").replace(".", "_")
    segs = [s for s in p.path.split("/") if s]
    tail = "_".join(segs[-2:]) if segs else "root"
    tail = re.sub(r"[^A-Za-z0-9_.-]+", "_", tail)[:80]
    return f"{host}__{tail}"


def summarize_json(payload):
    """One-line hint at what's in a JSON body: top-level keys + biggest list size."""
    if isinstance(payload, dict):
        keys = list(payload.keys())[:8]
        # Find the largest list reachable in the first two levels — that's
        # almost always the items array.
        best = ("", 0)
        def visit(node, path, depth):
            nonlocal best
            if depth > 2:
                return
            if isinstance(node, list):
                if len(node) > best[1]:
                    best = (path, len(node))
                return
            if isinstance(node, dict):
                for k, v in node.items():
                    visit(v, f"{path}.{k}" if path else k, depth + 1)
        visit(payload, "", 0)
        biggest = f"  biggest_list={best[0]}[{best[1]}]" if best[1] else ""
        return f"keys={keys}{biggest}"
    if isinstance(payload, list):
        return f"top-level list, len={len(payload)}"
    return f"scalar:{type(payload).__name__}"


async def auto_scroll(page) -> int:
    """Step-scroll down to mimic a human, so the load-more sentinel re-fires.

    On each tick: scroll by SCROLL_STEP_PX; if we're already pinned at the
    bottom, dwell a bit longer to give XHRs time to land + render. Stop
    when the page height has been unchanged AND we've been pinned at the
    bottom for STABLE_HEIGHT_TICKS consecutive ticks.
    """
    stable = 0
    last_height = 0
    for i in range(MAX_TICKS):
        snapshot = await page.evaluate(
            "() => ({y: window.scrollY, vp: window.innerHeight, h: document.documentElement.scrollHeight})"
        )
        at_bottom = snapshot["y"] + snapshot["vp"] >= snapshot["h"] - 4
        target = min(snapshot["y"] + SCROLL_STEP_PX, snapshot["h"])
        await page.evaluate(f"window.scrollTo({{top: {target}, behavior: 'instant'}})")

        if at_bottom:
            await page.wait_for_timeout(BOTTOM_DWELL_MS)
        else:
            await page.wait_for_timeout(SCROLL_TICK_MS)

        new_h = await page.evaluate("document.documentElement.scrollHeight")
        grew = new_h > snapshot["h"]

        # Concise log: only emit when something interesting changed.
        if grew or at_bottom or i % 10 == 0:
            tag = "+" if grew else ("=bottom" if at_bottom else "...")
            print(f"  tick {i + 1:>3}: y={snapshot['y']} h={snapshot['h']}->{new_h} {tag}")

        if at_bottom and not grew:
            stable += 1
            if stable >= STABLE_HEIGHT_TICKS:
                print(f"  bottom + height stable for {stable} ticks, stopping")
                return i + 1
        else:
            stable = 0
        last_height = new_h
    print(f"  hit MAX_TICKS={MAX_TICKS}, stopping")
    return MAX_TICKS


async def main(url: str):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # Wipe previous captures so the dir reflects only the current run.
    if CAPTURE_DIR.exists():
        for f in CAPTURE_DIR.iterdir():
            if f.is_file():
                f.unlink()
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    seq = 0
    saved = []  # (seq, status, host, path, summary)
    unique_item_ids: set[int] = set()

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        async def on_response(resp):
            nonlocal seq
            try:
                u = resp.url
                host = urlparse(u).hostname or ""
                if not HOST_PATTERN.search(host):
                    return
                ct = (resp.headers or {}).get("content-type", "")
                # Only keep JSON-ish bodies. Skip images/scripts/css to keep noise low.
                if "json" not in ct.lower() and not u.endswith(".json"):
                    return
                try:
                    body = await resp.body()
                except Exception:
                    return
                seq += 1
                this_seq = seq
                slug = slug_for(u)
                base = CAPTURE_DIR / f"{this_seq:03d}_{slug}"
                base.with_suffix(".json").write_bytes(body)

                # Try to parse + summarize. If parse fails, log raw size.
                summary = ""
                try:
                    payload = json.loads(body.decode("utf-8", errors="replace"))
                    summary = summarize_json(payload)
                except Exception:
                    summary = f"unparseable, {len(body)} bytes"

                # Save headers + URL alongside.
                meta = {
                    "url": u,
                    "status": resp.status,
                    "request_method": resp.request.method,
                    "request_headers": await resp.request.all_headers(),
                    "response_headers": resp.headers,
                }
                base.with_suffix(".headers.json").write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False)
                )

                path = urlparse(u).path
                saved.append((this_seq, resp.status, host, path, summary))

                # Live unique-item tally for the catalog endpoint.
                tally = ""
                if "campaignTppProducts" in path:
                    try:
                        items = payload.get("result", {}).get("data") or []
                        before = len(unique_item_ids)
                        for it in items:
                            aid = it.get("auctionId")
                            if aid is not None:
                                unique_item_ids.add(aid)
                        delta = len(unique_item_ids) - before
                        tally = f"  [+{delta} new, {len(unique_item_ids)} unique]"
                    except Exception:
                        pass

                print(f"[{this_seq:03d}] {resp.status} {host}{path[:80]}  {summary}{tally}")
            except Exception as e:
                print(f"  on_response error: {e!r}")

        page.on("response", on_response)

        print(f"Navigating to {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Let the SPA settle before we start scrolling.
        await page.wait_for_timeout(3000)

        print("Auto-scrolling to trigger infinite-scroll pagination...")
        scrolls = await auto_scroll(page)

        # One final pause to catch any in-flight XHRs.
        await page.wait_for_timeout(2000)

        print()
        print(f"Done. Scrolls={scrolls}, captured={len(saved)} JSON responses.")
        print(f"Captures in: {CAPTURE_DIR}")
        print()
        print("Summary table:")
        print(f"  {'#':>3}  {'status':>6}  host + path                                    summary")
        for s, status, host, path, summary in saved:
            print(f"  {s:>3}  {status:>6}  {host}{path[:60]:<60}  {summary}")

        print("\nLeaving browser open for 10s in case you want to inspect manually...")
        await page.wait_for_timeout(10000)
        await ctx.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/lazada_spike.py <shop-url>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
