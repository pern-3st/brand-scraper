"""LazadaScraper: Protocol-compliant platform scraper for lazada.sg.

Approach:

1. Open a persistent Chrome context via patchright (profile lives at
   ``backend/data/browser_profiles/lazada_sg``). Lazada doesn't gate
   shop pages behind a login wall, so no recovery handshake.
2. Attach a single ``page.on("response")`` listener that dispatches
   to:
     - ``MetadataResolver`` (lzdPcPageData + categories tree)
     - the catalog endpoints (any of the three known shapes — see
       ``extract.CATALOG_URL_FRAGMENTS``)
3. Navigate to the shop URL. Wait for both metadata sources (with a
   timeout — degrades to ID-only enrichment if either is missing).
4. Step-scroll the SPA (~700px ticks). The spike found that a naive
   ``scrollTo(0, scrollHeight)`` jump fires the load-more sentinel
   only once because the sentinel ends up above the viewport on the
   next jump. Step-scrolling keeps it cycling and lets each cookie-
   rotation cycle complete cleanly. See
   ``docs/plans/2026-05-06-lazada-spike-notes.md``.
5. The catalog listener parses each response and enqueues new-by-
   ``auctionId`` records into a local asyncio.Queue. The scroll loop
   drains that queue and yields after every tick. ``page.evaluate`` /
   ``wait_for_timeout`` aren't externally interruptible, so cancel
   checks happen on tick boundaries — not mid-evaluate.

Termination signal: page-height stable + viewport pinned at bottom for
~12 ticks (≈5s). Don't trust ``totalCount`` / ``totalPage`` — they're
unreliable (see the spike notes' Risk register).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from app.models import LazadaProductRecord
from app.platforms.base import ScrapeContext
from app.platforms.lazada._metadata import MetadataResolver
from app.platforms.lazada._session import launch_persistent_context
from app.platforms.lazada.extract import (
    is_catalog_url,
    map_item,
    parse_catalog_response,
    shop_handle_from_url,
)
from app.platforms.lazada.models import LazadaScrapeRequest

log = logging.getLogger(__name__)

# Step-scroll tunables — copied verbatim from the spike's verified
# values. The spike found that 700px ticks with 400ms pauses keeps the
# load-more sentinel cycling through the viewport naturally and lets
# each cookie-rotation cycle complete. See
# ``docs/plans/2026-05-06-lazada-spike-notes.md`` for the longer story.
SCROLL_STEP_PX = 700
SCROLL_TICK_MS = 400
BOTTOM_DWELL_MS = 1800
MAX_TICKS = 600
STABLE_HEIGHT_TICKS = 12  # ~5s pinned at bottom before we stop

# How long to wait for the lzdPcPageData + categories tree responses
# after navigation completes. If they don't arrive we proceed with
# whatever is resolved (brand_name / category_name will be left unset).
METADATA_TIMEOUT_S = 15.0


class LazadaScraper:
    sse_event_name = "product"
    platform_key = "lazada"

    def brand_slug(self, request: LazadaScrapeRequest) -> str:
        return shop_handle_from_url(str(request.shop_url))

    async def stream_products(
        self,
        request: LazadaScrapeRequest,
        ctx: ScrapeContext,
    ) -> AsyncIterator[LazadaProductRecord]:
        shop_url = str(request.shop_url)
        max_products = request.max_products

        seen_ids: set[int] = set()
        yielded = 0
        # The page.on("response") listener can't yield from an async
        # generator, so it pushes records onto this queue and the
        # scroll loop drains it.
        record_queue: asyncio.Queue[LazadaProductRecord] = asyncio.Queue()
        metadata = MetadataResolver()

        async def on_response(response: Any) -> None:
            url = response.url
            try:
                if metadata.url_matches(url):
                    payload = await response.json()
                    metadata.ingest(url, payload)
                    return
                if not is_catalog_url(url):
                    return
                payload = await response.json()
            except Exception:
                # Body unreadable / not JSON / connection cancelled —
                # routine for parallel SPA fetches, not worth logging.
                return

            items = parse_catalog_response(payload)
            if not items:
                return

            new_count = 0
            for raw in items:
                mapped = map_item(raw)
                if mapped is None:
                    continue
                item_id = mapped["item_id"]
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                metadata.enrich(mapped)
                rec = _to_record(mapped)
                if rec is None:
                    continue
                record_queue.put_nowait(rec)
                new_count += 1
            if new_count:
                log.info(
                    "lazada: catalog response added %d new items (total seen=%d)",
                    new_count, len(seen_ids),
                )

        async with launch_persistent_context() as (_p, context):
            page = context.pages[0] if context.pages else await context.new_page()
            page.on("response", on_response)

            log.info("lazada: navigating to %s", shop_url)
            await page.goto(shop_url, wait_until="domcontentloaded", timeout=60000)

            # Let the SPA settle so lzdPcPageData + categories XHRs fire.
            await metadata.wait_until_ready(timeout=METADATA_TIMEOUT_S)

            # Drain anything the listener has already queued (the initial
            # render often emits 1–2 catalog responses before the first
            # scroll tick).
            async for rec in _drain_queue(record_queue):
                if yielded >= max_products:
                    return
                if ctx.cancel_event.is_set():
                    return
                yielded += 1
                yield rec

            # Step-scroll loop. Each iteration: scroll one step, then
            # drain whatever the listener has produced. Cancel checks
            # happen on tick boundaries since page.evaluate /
            # wait_for_timeout aren't externally interruptible.
            stable = 0
            for tick in range(MAX_TICKS):
                if ctx.cancel_event.is_set():
                    log.info("lazada: cancelled at tick %d", tick)
                    return
                if yielded >= max_products:
                    log.info(
                        "lazada: reached max_products=%d, stopping", max_products,
                    )
                    return

                snapshot = await page.evaluate(
                    "() => ({y: window.scrollY, vp: window.innerHeight, "
                    "h: document.documentElement.scrollHeight})"
                )
                at_bottom = snapshot["y"] + snapshot["vp"] >= snapshot["h"] - 4
                target = min(snapshot["y"] + SCROLL_STEP_PX, snapshot["h"])
                await page.evaluate(
                    f"window.scrollTo({{top: {target}, behavior: 'instant'}})"
                )
                await page.wait_for_timeout(
                    BOTTOM_DWELL_MS if at_bottom else SCROLL_TICK_MS
                )

                new_h = await page.evaluate(
                    "document.documentElement.scrollHeight"
                )
                grew = new_h > snapshot["h"]

                # Drain whatever responses landed during this tick.
                async for rec in _drain_queue(record_queue):
                    if yielded >= max_products:
                        return
                    if ctx.cancel_event.is_set():
                        return
                    yielded += 1
                    yield rec

                # Termination: we trust scroll cadence, not server-side
                # totalCount/totalPage (verified unreliable in the spike).
                if at_bottom and not grew:
                    stable += 1
                    if stable >= STABLE_HEIGHT_TICKS:
                        log.info(
                            "lazada: bottom + height stable for %d ticks, stopping (yielded=%d)",
                            stable, yielded,
                        )
                        break
                else:
                    stable = 0
            else:
                log.info("lazada: hit MAX_TICKS=%d, stopping", MAX_TICKS)

            # Final drain — let any in-flight catalog responses land
            # before the context closes.
            await page.wait_for_timeout(2000)
            async for rec in _drain_queue(record_queue):
                if yielded >= max_products:
                    return
                if ctx.cancel_event.is_set():
                    return
                yielded += 1
                yield rec


async def _drain_queue(
    queue: asyncio.Queue[LazadaProductRecord],
) -> AsyncIterator[LazadaProductRecord]:
    while True:
        try:
            yield queue.get_nowait()
        except asyncio.QueueEmpty:
            return


def _to_record(item: dict) -> LazadaProductRecord | None:
    """Build a LazadaProductRecord from the mapped + metadata-enriched
    item dict. Returns None if pydantic validation rejects it (logged)."""
    try:
        return LazadaProductRecord(
            scraped_at=datetime.now(timezone.utc),
            **{k: v for k, v in item.items() if not k.startswith("_")},
        )
    except Exception as exc:
        log.warning("lazada: dropping malformed item %s: %s", item.get("item_id"), exc)
        return None
