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
   as a ProductRecord.
7. Terminate on: zero new item_ids after a navigation, `max_products`
   reached, ctx.cancel_event set, or navigation failure.

See docs/plans/2026-04-10-shopee-spike-notes.md for the full spike
reasoning including the rejected alternatives.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from app.platforms.base import ScrapeContext
from app.platforms.shopee._session import (
    CARD_WAIT_MS,
    PROFILE_DIR,
    launch_persistent_context,
    navigate_with_login_wall_recovery,
    wait_for_cards as _wait_for_cards,
)
from app.platforms.shopee.extract import (
    GRID_CARD_SELECTOR,
    extract_grid_items,
    shop_handle_from_url,
)
from app.models import ProductRecord
from app.platforms.shopee.models import ShopeeScrapeRequest

log = logging.getLogger(__name__)

# Re-exports for backwards compatibility — these moved to ``_session.py``
# but external code (and tests) historically imported them from here.
__all__ = [
    "PROFILE_DIR",
    "CARD_WAIT_MS",
    "ShopeeScraper",
]


class ShopeeScraper:
    sse_event_name = "product"
    platform_key = "shopee"

    def brand_slug(self, request: ShopeeScrapeRequest) -> str:
        return shop_handle_from_url(str(request.shop_url))

    async def stream_products(
        self,
        request: ShopeeScrapeRequest,
        ctx: ScrapeContext,
    ) -> AsyncIterator[ProductRecord]:
        shop_url = str(request.shop_url)
        max_products = request.max_products

        cumulative: set[int] = set()
        yielded = 0

        async with launch_persistent_context() as (_p, context):
            page = await context.new_page()

            # --- Page 1: navigate, recover from login wall if needed ---
            ready = await navigate_with_login_wall_recovery(page, shop_url, ctx)
            if not ready:
                return  # cancelled during login wait

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


def _to_record(item: dict) -> ProductRecord | None:
    """Convert an extract_grid_items dict into a ProductRecord.

    Returns None if required Shopee fields (item_id, product_name,
    product_url) are missing or malformed. The caller logs and skips.
    """
    try:
        return ProductRecord(
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
