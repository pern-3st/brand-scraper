"""Tests that `_run_job` correctly mutates an existing record on
`ProductUpdate` and emits a `product_update` SSE event."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models import ProductRecord, ProductUpdate
from app.runner import _run_job
from app.session import ScrapeSession


def _record(item_id: int, name: str = "X") -> ProductRecord:
    return ProductRecord(
        item_id=item_id,
        product_name=name,
        scraped_at=datetime.now(timezone.utc),
    )


async def _stream(items):
    for it in items:
        yield it


async def _collect_queue(session: ScrapeSession) -> list[dict]:
    events = []
    try:
        while True:
            ev = await asyncio.wait_for(session.queue.get(), timeout=0.5)
            if ev is None:
                break
            events.append(ev)
    except asyncio.TimeoutError:
        pass
    return events


def _job_kwargs(session: ScrapeSession, tmp_path: Path, stream) -> dict:
    return dict(
        session=session,
        partial_path=tmp_path / "partial.json",
        log_path=tmp_path / "log.txt",
        meta={},
        sse_event_name="product",
        stream=stream,
        finalize=lambda p: p,  # no rename in test
        compute_aggregates=lambda recs: {"product_count": len(recs)},
        done_payload=lambda recs, p: {"count": len(recs)},
        cancel_payload=lambda recs, p: {"count": len(recs)},
        error_payload=lambda exc, p: {"error": str(exc)},
    )


@pytest.mark.asyncio
async def test_product_update_mutates_record_and_emits_event(tmp_path: Path):
    session = ScrapeSession(id="t1", brand_id="b1", source_id="s1")

    items = [
        _record(1, "alpha"),
        _record(2, "beta"),
        ProductUpdate(item_id=1, monthly_sold_count=42, monthly_sold_text="42 sold"),
        ProductUpdate(item_id=999, monthly_sold_count=1),  # unknown id — must be dropped
    ]

    await _run_job(**_job_kwargs(session, tmp_path, _stream(items)))

    events = await _collect_queue(session)
    event_names = [e["event"] for e in events]
    assert event_names.count("product") == 2
    assert event_names.count("product_update") == 1
    assert "done" in event_names

    update_event = next(e for e in events if e["event"] == "product_update")
    payload = json.loads(update_event["data"])
    assert payload["item_id"] == 1
    assert payload["monthly_sold_count"] == 42
    assert payload["monthly_sold_text"] == "42 sold"

    final = json.loads((tmp_path / "partial.json").read_text())
    rec1 = next(r for r in final["records"] if r["item_id"] == 1)
    rec2 = next(r for r in final["records"] if r["item_id"] == 2)
    assert rec1["monthly_sold_count"] == 42
    assert rec1["monthly_sold_text"] == "42 sold"
    assert rec2["monthly_sold_count"] is None


@pytest.mark.asyncio
async def test_cancel_does_not_break_so_trailing_updates_drain(tmp_path: Path):
    """Regression test for the harvest-drain contract.

    The runner must NOT `break` on cancel — yielding inside an async
    generator's `finally:` block requires the consumer to keep iterating
    so the generator can exit normally rather than via GeneratorExit.

    Simulates a scraper that yields two records, then notices the cancel
    and runs its `finally:` block which yields a `ProductUpdate`. The
    runner must consume that update even though `cancel_event` is set.
    """
    session = ScrapeSession(id="t2", brand_id="b1", source_id="s1")

    async def scraper_like():
        try:
            yield _record(1, "alpha")
            # Cancel arrives before the next record. Scraper would
            # normally check ctx.cancel_event at the top of its loop and
            # return; we simulate that path:
            session.cancel_event.set()
            # No more records — return into finally.
            return
        finally:
            # Mirror the production scraper: emit harvested updates from
            # finally for items already yielded.
            yield ProductUpdate(item_id=1, monthly_sold_count=99, monthly_sold_text="99")

    await _run_job(**_job_kwargs(session, tmp_path, scraper_like()))

    events = await _collect_queue(session)
    event_names = [e["event"] for e in events]
    assert "cancelled" in event_names, event_names
    assert event_names.count("product_update") == 1, event_names

    final = json.loads((tmp_path / "partial.json").read_text())
    assert final["_status"] == "cancelled"
    rec1 = next(r for r in final["records"] if r["item_id"] == 1)
    assert rec1["monthly_sold_count"] == 99


@pytest.mark.asyncio
async def test_applies_rcmd_items_fields(tmp_path):
    """ProductUpdate carries category_id/brand/likes/promos/voucher_code/
    voucher_discount; runner must apply each via the `if x is not None`
    guard. NOTE: `category` (display name) is intentionally NOT in the
    update — Shopee's harvest leaves that field for the official-site path."""
    session = ScrapeSession(id="t3", brand_id="b1", source_id="s1")
    rec = _record(42, "Boot")
    upd = ProductUpdate(
        item_id=42,
        monthly_sold_count=15,
        monthly_sold_text="15 Sold/Month",
        category_id="100011",
        brand="Levi's",
        liked_count=260,
        promotion_labels=["Any 2 enjoy 5% off"],
        voucher_code="9OFF70",
        voucher_discount=900000,
    )
    await _run_job(**_job_kwargs(session, tmp_path, _stream([rec, upd])))
    final = json.loads((tmp_path / "partial.json").read_text())
    prod = next(r for r in final["records"] if r["item_id"] == 42)
    assert prod["category_id"] == "100011"
    assert prod["category"] is None  # untouched — Shopee does not write display name
    assert prod["brand"] == "Levi's"
    assert prod["liked_count"] == 260
    assert prod["promotion_labels"] == ["Any 2 enjoy 5% off"]
    assert prod["voucher_code"] == "9OFF70"
    assert prod["voucher_discount"] == 900000
    assert prod["monthly_sold_count"] == 15
    assert prod["monthly_sold_text"] == "15 Sold/Month"
