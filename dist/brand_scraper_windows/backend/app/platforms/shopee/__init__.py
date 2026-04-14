"""ShopeeScraper: Protocol-compliant platform scraper for shopee.sg.

Promoted from the 2026-04-10 spike (backend/scripts/shopee_spike.py).
Approach:

1. Open a persistent Chrome context via patchright (profile lives at
   backend/data/browser_profiles/shopee_sg; first run needs manual login
   in the opened window, subsequent runs reuse cookies).
2. Navigate to the shop URL (page 1 is the bare URL; pages 2+ use
   ?page=N&sortBy=pop&tab=0 — confirmed via click-URL logging in the spike).
3. After each navigation, wait for GRID_CARD_SELECTOR with a 10s timeout.
   Cards are SSR'd so they're there at domcontentloaded in practice.
4. If page 1 times out: assume login wall. Emit `login_required` on the
   SSE queue, await ctx.login_event or ctx.cancel_event, then retry the
   navigation once. If it times out again, raise — the user will need to
   inspect the open browser window.
5. Extract per-card fields with a single page.evaluate(EXTRACT_JS) call.
6. Dedupe against a cumulative set of item_ids. Yield each new record
   as a ShopeeProductRecord.
7. Terminate on: zero new item_ids after a navigation, `max_products`
   reached, ctx.cancel_event set, or navigation failure.

See docs/plans/2026-04-10-shopee-spike-notes.md for the full spike
reasoning including the rejected alternatives.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from patchright.async_api import async_playwright

from app.platforms.base import ScrapeContext
from app.platforms.shopee.extract import (
    GRID_CARD_SELECTOR,
    extract_grid_items,
    shop_handle_from_url,
)
from app.platforms.shopee.models import ShopeeProductRecord, ShopeeScrapeRequest

log = logging.getLogger(__name__)

# Resolve to backend/data/browser_profiles/shopee_sg. File layout:
#   backend/app/platforms/shopee/__init__.py
#   parents[0] = shopee/  parents[1] = platforms/
#   parents[2] = app/     parents[3] = backend/
BACKEND_ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = BACKEND_ROOT / "data" / "browser_profiles" / "shopee_sg"

CARD_WAIT_MS = 10_000


class ShopeeScraper:
    sse_event_name = "product"
    platform_key = "shopee"

    def brand_slug(self, request: ShopeeScrapeRequest) -> str:
        return shop_handle_from_url(str(request.shop_url))

    async def stream_products(
        self,
        request: ShopeeScrapeRequest,
        ctx: ScrapeContext,
    ) -> AsyncIterator[ShopeeProductRecord]:
        shop_url = str(request.shop_url)
        max_products = request.max_products
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        cumulative: set[int] = set()
        yielded = 0

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=False,
                viewport={"width": 1366, "height": 900},
            )
            try:
                page = await context.new_page()

                # --- Page 1: navigate, check for login wall ---
                await page.goto(shop_url, wait_until="domcontentloaded")
                if not await _wait_for_cards(page):
                    log.info("shopee: no grid cards on first load — assuming login wall")
                    ctx.queue.put_nowait({
                        "event": "login_required",
                        "data": json.dumps({
                            "message": (
                                "Log in to Shopee in the open Chrome window, "
                                "then click Continue."
                            ),
                        }),
                    })
                    login_task = asyncio.create_task(ctx.login_event.wait())
                    cancel_task = asyncio.create_task(ctx.cancel_event.wait())
                    done, pending = await asyncio.wait(
                        [login_task, cancel_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
                    if ctx.cancel_event.is_set():
                        return
                    ctx.login_event.clear()

                    await page.goto(shop_url, wait_until="domcontentloaded")
                    if not await _wait_for_cards(page):
                        raise RuntimeError(
                            "shopee: still no grid cards after login. "
                            "Check the shop URL or inspect the browser window."
                        )

                # --- Paginate until exhausted or limit reached ---
                page_idx = 1
                while True:
                    if ctx.cancel_event.is_set():
                        return

                    items = await extract_grid_items(page)
                    new_items = [
                        it for it in items if it.get("item_id") not in cumulative
                    ]
                    log.info(
                        "shopee: page=%d extracted=%d new=%d cumulative=%d",
                        page_idx, len(items), len(new_items), len(cumulative),
                    )

                    if not new_items:
                        log.info("shopee: zero new items — catalog exhausted")
                        return

                    for it in new_items:
                        if yielded >= max_products:
                            return
                        rec = _to_record(it)
                        if rec is None:
                            log.warning("shopee: dropping malformed card %s", it)
                            continue
                        cumulative.add(rec.item_id)
                        yielded += 1
                        yield rec

                    if yielded >= max_products:
                        return

                    page_idx += 1
                    target = f"{shop_url}?page={page_idx}&sortBy=pop&tab=0"
                    try:
                        await page.goto(target, wait_until="domcontentloaded")
                    except Exception as exc:
                        log.info(
                            "shopee: nav to page %d failed (%s) — stopping",
                            page_idx, exc,
                        )
                        return
                    if not await _wait_for_cards(page):
                        log.info(
                            "shopee: page %d has no grid cards — catalog exhausted",
                            page_idx,
                        )
                        return
            finally:
                await context.close()


async def _wait_for_cards(page) -> bool:
    """Wait for at least one grid card. Returns True on success, False on timeout."""
    try:
        await page.wait_for_selector(GRID_CARD_SELECTOR, timeout=CARD_WAIT_MS)
        return True
    except Exception:
        return False


def _to_record(item: dict) -> ShopeeProductRecord | None:
    """Convert an extract_grid_items dict into a ShopeeProductRecord.

    Returns None if required fields (item_id, product_name, product_url)
    are missing or malformed. The caller logs and skips.
    """
    try:
        return ShopeeProductRecord(
            item_id=int(item["item_id"]),
            product_name=str(item["product_name"]),
            product_url=str(item["product_url"]),
            image_url=item.get("image_url"),
            price=item.get("price"),
            mrp=item.get("mrp"),
            currency="SGD",
            discount_pct=item.get("discount_pct"),
            rating_star=item.get("rating_star"),
            historical_sold_count=item.get("historical_sold_count"),
            is_sold_out=bool(item.get("is_sold_out", False)),
            scraped_at=datetime.now(timezone.utc),
        )
    except (KeyError, TypeError, ValueError):
        return None
