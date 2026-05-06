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
from typing import Any, AsyncIterator, Callable

from pydantic import BaseModel, TypeAdapter

from app.brands import BrandRepo, compute_run_aggregates, new_enrichment_id
from app.models import (
    EnrichmentRequest,
    EnrichmentRow,
    RECORD_CLASSES,
    ScrapeRequest,
    ShopeeProductUpdate,
)
from app.platforms.base import (
    EnrichmentExtractor,
    ProductIdentity,
    ScrapeContext,
)
from app.platforms.lazada.identity import LazadaProductIdentity
from app.platforms.lazada.scraper import LazadaScraper
from app.platforms.official_site import OfficialSiteScraper
from app.platforms.official_site_enrichment import (
    OfficialSiteEnrichment,
    OfficialSiteProductIdentity,
)
from app.platforms.shopee.enrichment import (
    ShopeeEnrichment,
    ShopeeProductIdentity,
)
from app.platforms.shopee.scraper import ShopeeScraper
from app.session import (
    ScrapeSession,
    attach_queue_log_handler,
    current_session_id,
    detach_queue_log_handler,
)
from app.storage import timestamp, write_records

log = logging.getLogger(__name__)

PLATFORMS = {
    "official_site": OfficialSiteScraper,
    "shopee": ShopeeScraper,
    "lazada": LazadaScraper,
}

# Enrichment registries — populated alongside each platform's extractor.
ENRICHMENT_EXTRACTORS: dict[str, type[EnrichmentExtractor]] = {
    "official_site": OfficialSiteEnrichment,
    "shopee": ShopeeEnrichment,
}
PRODUCT_IDENTITIES: dict[str, ProductIdentity] = {
    "official_site": OfficialSiteProductIdentity(),
    "shopee": ShopeeProductIdentity(),
    "lazada": LazadaProductIdentity(),
}

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "brands"
_repo = BrandRepo(root=DATA_ROOT)
_request_adapter = TypeAdapter(ScrapeRequest)


def get_repo() -> BrandRepo:
    return _repo


async def _run_job(
    *,
    session: ScrapeSession,
    partial_path: Path,
    log_path: Path,
    meta: dict[str, Any],
    sse_event_name: str,
    stream: AsyncIterator[BaseModel],
    finalize: Callable[[Path], Path],
    compute_aggregates: Callable[[list[BaseModel]], dict[str, Any]],
    done_payload: Callable[[list[BaseModel], Path], dict[str, Any]],
    cancel_payload: Callable[[list[BaseModel], Path], dict[str, Any]],
    error_payload: Callable[[Exception, Path], dict[str, Any]],
    record_key: str = "records",
    to_event_data: Callable[[BaseModel, int], Any] | None = None,
) -> None:
    """Shared job shell: stream items, flush per item, emit SSE, handle
    cancel/error/done uniformly. Used by both ``run_scrape`` and
    ``run_enrichment`` so the partial-flush + SSE plumbing only lives in
    one place.

    ``record_key`` controls the top-level list name in the partial/final
    file (``records`` for scrapes, ``results`` for enrichments).
    ``to_event_data`` optionally transforms ``(item, index)`` into the SSE
    payload; defaults to ``item.model_dump(mode="json")`` so scrapes keep
    their existing wire shape.
    """
    session.queue.set_log_path(log_path)
    # Bind the session id in this task's context so SessionLogFilter on the
    # attached handler can distinguish records belonging to this run from
    # records belonging to another run happening concurrently. _run_job is
    # always entered as an asyncio Task via main.py, so setting the var here
    # does not bleed into other tasks.
    token = current_session_id.set(session.id)
    handler = attach_queue_log_handler(session.queue, session_id=session.id)
    records: list[BaseModel] = []
    status = "ok"

    def flush(current_status: str) -> None:
        write_records(partial_path, records, meta=meta, status=current_status, record_key=record_key)

    def event_payload(item: BaseModel, idx: int) -> Any:
        if to_event_data is None:
            return item.model_dump(mode="json")
        return to_event_data(item, idx)

    try:
        try:
            async for item in stream:
                if session.cancel_event.is_set():
                    # Mark the run as cancelled but DO NOT break. The Shopee
                    # scraper's stream_products yields harvested
                    # ShopeeProductUpdate values from its `finally:` block —
                    # yielding inside finally raises
                    # RuntimeError("async generator ignored GeneratorExit")
                    # if the consumer breaks first. Letting the loop drain lets
                    # the scraper's own ctx.cancel_event check at the top of its
                    # grid loop short-circuit naturally, run finally cleanly,
                    # and deliver any harvested updates before the generator
                    # ends. See plan header "Cancellation contract".
                    status = "cancelled"
                if isinstance(item, ShopeeProductUpdate):
                    target = next(
                        (r for r in records if r.item_id == item.item_id),
                        None,
                    )
                    if target is None:
                        log.warning(
                            "runner: ShopeeProductUpdate for unknown item_id=%s — dropped",
                            item.item_id,
                        )
                        continue
                    if item.monthly_sold_count is not None:
                        target.monthly_sold_count = item.monthly_sold_count
                    if item.monthly_sold_text is not None:
                        target.monthly_sold_text = item.monthly_sold_text
                    if item.category_id is not None:
                        target.category_id = item.category_id
                    if item.brand is not None:
                        target.brand = item.brand
                    if item.liked_count is not None:
                        target.liked_count = item.liked_count
                    if item.promotion_labels is not None:
                        target.promotion_labels = item.promotion_labels
                    if item.voucher_code is not None:
                        target.voucher_code = item.voucher_code
                    if item.voucher_discount is not None:
                        target.voucher_discount = item.voucher_discount
                    flush("in_progress")
                    session.queue.put_nowait({
                        "event": "product_update",
                        "data": json.dumps(item.model_dump(mode="json")),
                    })
                    continue
                records.append(item)
                flush("in_progress")
                session.queue.put_nowait({
                    "event": sse_event_name,
                    "data": json.dumps(event_payload(item, len(records))),
                })

            meta["aggregates"] = compute_aggregates(records)

            if status == "ok":
                flush("ok")
                final = finalize(partial_path)
                session.queue.put_nowait({
                    "event": "done",
                    "data": json.dumps(done_payload(records, final)),
                })
            elif status == "cancelled":
                flush("cancelled")
                session.queue.put_nowait({
                    "event": "cancelled",
                    "data": json.dumps(cancel_payload(records, partial_path)),
                })
        except Exception as exc:
            log.exception("job failed")
            meta["error"] = str(exc)
            flush("error")
            session.queue.put_nowait({
                "event": "error",
                "data": json.dumps(error_payload(exc, partial_path)),
            })
    finally:
        detach_queue_log_handler(handler)
        current_session_id.reset(token)
        session.queue.close()


async def run_scrape(session: ScrapeSession) -> None:
    repo = get_repo()
    source = repo.get_source(session.brand_id, session.source_id)
    if source is None:
        session.queue.put_nowait({
            "event": "error",
            "data": json.dumps({"message": f"source {session.source_id} not found"}),
        })
        session.queue.close()
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
        session.queue.close()
        return

    scraper = PLATFORMS[source.platform]()
    ctx = ScrapeContext(
        cancel_event=session.cancel_event,
        login_event=session.login_event,
        queue=session.queue,
    )

    ts = timestamp()
    log_path = repo.log_path(session.brand_id, session.source_id, ts)
    partial = repo.partial_run_path(session.brand_id, session.source_id, ts)
    meta: dict[str, Any] = {
        "platform": source.platform,
        "brand_id": session.brand_id,
        "source_id": session.source_id,
        "started_at": ts,
        "request": request.model_dump(mode="json"),
    }

    def _aggregates(records: list[BaseModel]) -> dict[str, Any]:
        return compute_run_aggregates(
            records=[r.model_dump(mode="json") for r in records],
        )

    def _done(records: list[BaseModel], final: Path) -> dict[str, Any]:
        return {
            "brand_id": session.brand_id,
            "source_id": session.source_id,
            "run_id": ts,
            "count": len(records),
            "file": str(final),
        }

    def _cancel(records: list[BaseModel], partial_p: Path) -> dict[str, Any]:
        return {
            "brand_id": session.brand_id,
            "source_id": session.source_id,
            "run_id": ts,
            "count": len(records),
            "file": str(partial_p),
        }

    def _error(exc: Exception, partial_p: Path) -> dict[str, Any]:
        return {"message": str(exc), "file": str(partial_p)}

    await _run_job(
        session=session,
        partial_path=partial,
        log_path=log_path,
        meta=meta,
        sse_event_name=scraper.sse_event_name,
        stream=scraper.stream_products(request, ctx),
        finalize=repo.finalize_run,
        compute_aggregates=_aggregates,
        done_payload=_done,
        cancel_payload=_cancel,
        error_payload=_error,
    )


async def run_enrichment(session: ScrapeSession) -> None:
    """Per-session entry point for an enrichment pass.

    Requires ``session.parent_run_id`` and ``session.request`` to be set
    (main.py populates them when dispatching ``POST /enrichments``). Mirrors
    ``run_scrape`` via ``_run_job`` — the only differences are the parent-
    status gate, the enrichment ID, the file-layout, and the SSE vocabulary.
    """
    repo = get_repo()

    parent_run_id = session.parent_run_id
    request = session.request
    if parent_run_id is None or request is None:
        _emit_fatal(session, "enrichment session missing parent_run_id/request")
        return

    parent = repo.get_run_payload(session.brand_id, session.source_id, parent_run_id)
    if parent is None:
        _emit_fatal(session, f"parent run {parent_run_id!r} not found")
        return
    parent_status = parent.get("_status")
    if parent_status not in {"ok", "cancelled"}:
        _emit_fatal(
            session,
            f"parent run {parent_run_id!r} is {parent_status!r}; enrichment requires ok/cancelled",
        )
        return

    platform = (parent.get("_meta") or {}).get("platform")
    if platform not in ENRICHMENT_EXTRACTORS:
        _emit_fatal(session, f"platform {platform!r} does not support enrichment")
        return
    extractor = ENRICHMENT_EXTRACTORS[platform]()
    identity = PRODUCT_IDENTITIES[platform]
    record_cls = RECORD_CLASSES[platform]

    try:
        records = [record_cls.model_validate(r) for r in parent.get("records", []) or []]
    except Exception as exc:
        log.exception("failed to load parent run records")
        _emit_fatal(session, f"could not read parent run records: {exc}")
        return

    total_products = len(records)
    skipped_no_key = sum(1 for r in records if identity.product_key(r) is None)

    requested_fields = list(request.curated_fields) + [p.id for p in request.freeform_prompts]

    # Skip products whose every requested field is already populated by a
    # prior enrichment pass on this parent run. Failures (rows with
    # errors["_all"] or null fields) are NOT in the map, so they get retried.
    enriched_map = repo.enriched_field_map(
        session.brand_id, session.source_id, parent_run_id
    )

    def _is_already_enriched(record: Any) -> bool:
        pk = identity.product_key(record)
        if pk is None:
            return False
        have = enriched_map.get(pk, set())
        return all(fid in have for fid in requested_fields)

    skipped_already = sum(1 for r in records if _is_already_enriched(r))
    records_to_run = [r for r in records if not _is_already_enriched(r)]

    enrichment_id = new_enrichment_id()
    log_path = repo.enrichment_log_path(
        session.brand_id, session.source_id, parent_run_id, enrichment_id,
    )
    partial = repo.partial_enrichment_path(
        session.brand_id, session.source_id, parent_run_id, enrichment_id,
    )
    meta: dict[str, Any] = {
        "platform": platform,
        "brand_id": session.brand_id,
        "source_id": session.source_id,
        "parent_run_id": parent_run_id,
        "started_at": enrichment_id,
        "request": request.model_dump(mode="json"),
    }

    # Emit the started banner once before streaming begins. Frontend uses
    # this to size its progress bar (index/total per ``enrichment_row``).
    session.queue.put_nowait({
        "event": "enrichment_started",
        "data": json.dumps({
            "enrichment_id": enrichment_id,
            "total_products": total_products,
            "products_skipped_no_key": skipped_no_key,
            "products_skipped_already_enriched": skipped_already,
            "requested_fields": requested_fields,
        }),
    })

    ctx = ScrapeContext(
        cancel_event=session.cancel_event,
        login_event=session.login_event,
        queue=session.queue,
    )

    def _aggregates(rows: list[BaseModel]) -> dict[str, Any]:
        attempted = len(rows)
        enriched = 0
        failed = 0
        for r in rows:
            assert isinstance(r, EnrichmentRow)
            has_all_error = "_all" in (r.errors or {})
            if has_all_error or not r.values:
                failed += 1
            else:
                enriched += 1
        return {
            "products_attempted": attempted,
            "products_enriched": enriched,
            "products_failed": failed,
            "products_skipped_no_key": skipped_no_key,
            "products_skipped_already_enriched": skipped_already,
        }

    def _done(rows: list[BaseModel], final: Path) -> dict[str, Any]:
        return {
            "brand_id": session.brand_id,
            "source_id": session.source_id,
            "run_id": parent_run_id,
            "enrichment_id": enrichment_id,
            "count": len(rows),
            "file": str(final),
        }

    def _cancel(rows: list[BaseModel], partial_p: Path) -> dict[str, Any]:
        return {
            "brand_id": session.brand_id,
            "source_id": session.source_id,
            "run_id": parent_run_id,
            "enrichment_id": enrichment_id,
            "count": len(rows),
            "file": str(partial_p),
        }

    def _error(exc: Exception, partial_p: Path) -> dict[str, Any]:
        return {
            "message": str(exc),
            "enrichment_id": enrichment_id,
            "file": str(partial_p),
        }

    def _to_event(item: BaseModel, idx: int) -> dict[str, Any]:
        assert isinstance(item, EnrichmentRow)
        return {
            "product_key": item.product_key,
            "values": item.values,
            "errors": item.errors,
            "index": idx,
            "total": total_products - skipped_no_key - skipped_already,
        }

    await _run_job(
        session=session,
        partial_path=partial,
        log_path=log_path,
        meta=meta,
        sse_event_name="enrichment_row",
        stream=extractor.stream_enrichments(records_to_run, request, ctx),
        finalize=repo.finalize_enrichment,
        compute_aggregates=_aggregates,
        done_payload=_done,
        cancel_payload=_cancel,
        error_payload=_error,
        record_key="results",
        to_event_data=_to_event,
    )


def _emit_fatal(session: ScrapeSession, message: str) -> None:
    """Emit a one-shot `error` event and close the queue. Used for pre-flight
    failures in ``run_enrichment`` that happen before ``_run_job`` takes over
    (so its ``finally: queue.close()`` isn't engaged yet)."""
    session.queue.put_nowait({
        "event": "error",
        "data": json.dumps({"message": message}),
    })
    session.queue.close()
