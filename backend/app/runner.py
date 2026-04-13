"""Platform-agnostic scrape runner.

Responsibilities:
- Pick the platform scraper from the registry.
- Iterate its stream_products async generator.
- For each yielded record: append to an in-memory list, write the partial
  file, and emit the scraper's per-item SSE event.
- On clean finish: emit `done` and rename partial → final.
- On cancel / error: emit matching event, leave partial file with status.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.platforms.base import ScrapeContext
from app.platforms.official_site import OfficialSiteScraper
from app.platforms.shopee import ShopeeScraper
from app.session import ScrapeSession
from app.storage import finalize, partial_path, timestamp, write_records

log = logging.getLogger(__name__)

PLATFORMS = {
    "official_site": OfficialSiteScraper,
    "shopee": ShopeeScraper,
}


async def run_scrape(session: ScrapeSession) -> None:
    request = session.request
    scraper = PLATFORMS[request.platform]()
    ctx = ScrapeContext(
        cancel_event=session.cancel_event,
        login_event=session.login_event,
        queue=session.queue,
    )

    brand_slug = scraper.brand_slug(request)
    ts = timestamp()
    partial = partial_path(scraper.platform_key, brand_slug, ts)
    meta: dict[str, Any] = {
        "platform": scraper.platform_key,
        "brand": brand_slug,
        "started_at": ts,
        "request": request.model_dump(mode="json"),
    }
    records: list = []
    status = "ok"

    def flush(current_status: str) -> None:
        write_records(partial, records, meta=meta, status=current_status)

    try:
        async for record in scraper.stream_products(request, ctx):
            if ctx.cancel_event.is_set():
                status = "cancelled"
                break
            records.append(record)
            flush("in_progress")
            session.queue.put_nowait({
                "event": scraper.sse_event_name,
                "data": json.dumps(record.model_dump(mode="json")),
            })
        else:
            # generator exhausted cleanly
            status = "ok"

        if status == "ok":
            flush("ok")
            final = finalize(partial)
            session.queue.put_nowait({
                "event": "done",
                "data": json.dumps({
                    "brand": brand_slug,
                    "count": len(records),
                    "file": str(final),
                }),
            })
        elif status == "cancelled":
            flush("cancelled")
            session.queue.put_nowait({
                "event": "cancelled",
                "data": json.dumps({
                    "brand": brand_slug,
                    "count": len(records),
                    "file": str(partial),
                }),
            })
    except Exception as exc:
        log.exception("scrape failed")
        flush("error")
        session.queue.put_nowait({
            "event": "error",
            "data": json.dumps({"message": str(exc), "file": str(partial)}),
        })
