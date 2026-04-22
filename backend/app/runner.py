"""Platform-agnostic scrape runner.

Responsibilities:
- Look up the stored source for {brand_id, source_id}.
- Rebuild a typed request from source.spec via the pydantic discriminated union.
- Pick the platform scraper from the registry.
- Iterate its stream_products async generator.
- For each yielded record: append, write the partial file, emit per-item SSE.
- On clean finish: compute+nest aggregates into _meta, emit `done`, rename
  partial → final.
- On cancel / error: emit matching event, leave partial file with status.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.brands import BrandRepo, compute_run_aggregates
from app.models import ScrapeRequest
from app.platforms.base import ScrapeContext
from app.platforms.official_site import OfficialSiteScraper
from app.platforms.shopee.scraper import ShopeeScraper
from app.session import ScrapeSession
from app.storage import timestamp, write_records

log = logging.getLogger(__name__)

PLATFORMS = {
    "official_site": OfficialSiteScraper,
    "shopee": ShopeeScraper,
}

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "brands"
_repo = BrandRepo(root=DATA_ROOT)
_request_adapter = TypeAdapter(ScrapeRequest)


def get_repo() -> BrandRepo:
    return _repo


async def run_scrape(session: ScrapeSession) -> None:
    repo = get_repo()
    source = repo.get_source(session.brand_id, session.source_id)
    if source is None:
        session.queue.put_nowait({
            "event": "error",
            "data": json.dumps({"message": f"source {session.source_id} not found"}),
        })
        return

    try:
        request = _request_adapter.validate_python(
            {"platform": source.platform, **source.spec}
        )
    except Exception as exc:
        log.exception("invalid source spec")
        session.queue.put_nowait({
            "event": "error",
            "data": json.dumps({"message": f"invalid source spec: {exc}"}),
        })
        return

    scraper = PLATFORMS[source.platform]()
    ctx = ScrapeContext(
        cancel_event=session.cancel_event,
        login_event=session.login_event,
        queue=session.queue,
    )

    ts = timestamp()
    partial = repo.partial_run_path(session.brand_id, session.source_id, ts)
    meta: dict[str, Any] = {
        "platform": source.platform,
        "brand_id": session.brand_id,
        "source_id": session.source_id,
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
            status = "ok"

        # On finalize, nest aggregates under _meta["aggregates"] so
        # misc meta fields (request, started_at, platform, ids) stay separate.
        record_dicts = [r.model_dump(mode="json") for r in records]
        meta["aggregates"] = compute_run_aggregates(records=record_dicts)

        if status == "ok":
            flush("ok")
            final = repo.finalize_run(partial)
            session.queue.put_nowait({
                "event": "done",
                "data": json.dumps({
                    "brand_id": session.brand_id,
                    "source_id": session.source_id,
                    "run_id": ts,
                    "count": len(records),
                    "file": str(final),
                }),
            })
        elif status == "cancelled":
            flush("cancelled")
            session.queue.put_nowait({
                "event": "cancelled",
                "data": json.dumps({
                    "brand_id": session.brand_id,
                    "source_id": session.source_id,
                    "run_id": ts,
                    "count": len(records),
                    "file": str(partial),
                }),
            })
    except Exception as exc:
        log.exception("scrape failed")
        meta["error"] = str(exc)
        flush("error")
        session.queue.put_nowait({
            "event": "error",
            "data": json.dumps({"message": str(exc), "file": str(partial)}),
        })
