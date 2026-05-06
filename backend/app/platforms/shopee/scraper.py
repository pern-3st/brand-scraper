"""ShopeeScraper: Protocol-compliant platform scraper for shopee.sg.

Approach:

1. Open a persistent Chrome context via patchright (profile lives at
   backend/data/browser_profiles/shopee_sg; first run needs manual login
   in the opened window, subsequent runs reuse cookies).
2. Navigate to the shop URL (page 1 is the bare URL; pages 2+ use
   ?page=N&sortBy=pop&tab=0).
3. After each navigation, wait for GRID_CARD_SELECTOR with a 10s timeout.
4. Extract per-card fields with a single page.evaluate(EXTRACT_JS) call.
5. Dedupe against a cumulative set of item_ids. Yield each new record
   as a ShopeeProductRecord with late-arriving fields left as None.
6. Terminate on: zero new item_ids after a navigation, max_products
   reached, ctx.cancel_event set, or navigation failure.

Late-arriving harvest (2026-05-05): a `page.on("response")` listener
fills a background `harvest` dict from Shopee's `/api/v4/shop/rcmd_items`
XHR which fires automatically on every grid nav. At end-of-stream
(in `finally:` so cancellation doesn't lose data), one ShopeeProductUpdate
is yielded per harvested item carrying monthly_sold + category_id +
brand + liked_count + promotion_labels + voucher_code + voucher_discount.
The runner mutates the matching record. Replaced the older recommend-XHR
seed-PDP mechanism — see docs/plans/2026-05-05-shopee-rcmd-items-migration.md.
The display-name (`category`) field is NOT populated by this path; the
catid space here is unresolvable on shopee.sg's public API (Task 4 SKIPPED).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import AsyncIterator

from app.models import ShopeeProductRecord, ShopeeProductUpdate
from app.platforms.base import ScrapeContext
from app.platforms.shopee._rcmd_items_harvest import (
    HarvestEntry,
    merge_into_harvest,
    parse_rcmd_items,
)
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
from app.platforms.shopee.models import ShopeeScrapeRequest

log = logging.getLogger(__name__)

# Re-exports for backwards compatibility — these moved to ``_session.py``
# but external code (and tests) historically imported them from here.
__all__ = [
    "PROFILE_DIR",
    "CARD_WAIT_MS",
    "ShopeeScraper",
]

# Endpoint we tap for late-arriving per-item metadata. Fires automatically
# on every shop-grid navigation; no PDP visits required (replaces the
# previous PDP-seed approach — see docs/plans/2026-05-05-shopee-rcmd-items-migration.md).
RCMD_ITEMS_URL_FRAGMENT = "/api/v4/shop/rcmd_items"


class ShopeeScraper:
    sse_event_name = "product"
    platform_key = "shopee"

    def brand_slug(self, request: ShopeeScrapeRequest) -> str:
        return shop_handle_from_url(str(request.shop_url))

    async def stream_products(
        self,
        request: ShopeeScrapeRequest,
        ctx: ScrapeContext,
    ) -> AsyncIterator[ShopeeProductRecord | ShopeeProductUpdate]:
        shop_url = str(request.shop_url)
        max_products = request.max_products

        cumulative: set[int] = set()
        yielded = 0
        harvest: dict[int, HarvestEntry] = {}

        async def on_response(response):
            if RCMD_ITEMS_URL_FRAGMENT not in response.url:
                return
            try:
                data = await response.json()
            except Exception:
                return
            parsed = parse_rcmd_items(data)
            added = merge_into_harvest(harvest, parsed)
            if added:
                covered = sum(
                    1 for v in harvest.values() if v.monthly_text is not None
                )
                log.info(
                    "shopee: rcmd_items harvested monthly for %d items "
                    "(harvest=%d, covered=%d)",
                    added, len(harvest), covered,
                )

        async with launch_persistent_context() as (_p, context):
            page = await context.new_page()
            page.on("response", on_response)

            ready = await navigate_with_login_wall_recovery(page, shop_url, ctx)
            if not ready:
                return  # cancelled during login wait

            try:
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
                            "shopee: page %d has no grid cards — exhausted",
                            page_idx,
                        )
                        return
            finally:
                # Drain harvested late-arriving fields as ShopeeProductUpdate events.
                # Runs on clean exit, limit-reached, AND cancellation —
                # provided the runner does NOT break the async-for loop on
                # cancel (see runner.py:124-132 / "Cancellation contract").
                # Only emit for items we actually yielded (cumulative set).
                # `category` (display name) is intentionally NOT set —
                # see docs/plans/2026-05-05-shopee-rcmd-items-migration.md
                # Task 4 (SKIPPED).
                update_count = 0
                for iid in cumulative:
                    h = harvest.get(iid)
                    if not h:
                        continue
                    yield ShopeeProductUpdate(
                        item_id=iid,
                        monthly_sold_count=h.monthly_int,
                        monthly_sold_text=h.monthly_text,
                        category_id=str(h.catid) if h.catid is not None else None,
                        brand=h.brand,
                        liked_count=h.liked_count,
                        promotion_labels=h.promotion_labels or None,
                        voucher_code=h.voucher_code,
                        voucher_discount=h.voucher_discount,
                    )
                    update_count += 1
                log.info(
                    "shopee: emitted %d ShopeeProductUpdate events "
                    "(harvest=%d, grid_items=%d)",
                    update_count, len(harvest), len(cumulative),
                )


def _to_record(item: dict) -> ShopeeProductRecord | None:
    """Convert an extract_grid_items dict into a ShopeeProductRecord.

    Returns None if required Shopee fields (item_id, product_name,
    product_url) are missing or malformed. The caller logs and skips.
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
