"""Integration tests for Phase 4: enrichment endpoints + run_enrichment.

Two layers:

1. ``run_enrichment`` is exercised directly via ``asyncio.run`` so the
   partial-flush, aggregate computation, SSE vocabulary, and parent-
   status gate are all verified without the TestClient event-loop portal
   getting in the way.

2. The HTTP endpoints are exercised via the shared ``client`` fixture,
   with ``app.main.run_enrichment`` mocked out so the request layer is
   tested in isolation from the background task.
"""
from __future__ import annotations

import asyncio
import json
import logging as _logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import pytest

from app import main as app_main
from app import runner
from app.brands import ENRICHMENT_DIR_SUFFIX
from app.models import EnrichmentRequest, EnrichmentRow, FieldDef
from app.platforms.base import ScrapeContext
from app.runner import run_enrichment
from app.session import ScrapeSession, _CAPTURED_LOGGERS, sessions


# --- fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_session_table():
    """Ensure no cross-test session pollution (FastAPI module-level dict)."""
    sessions.clear()
    yield
    sessions.clear()


@pytest.fixture
def seeded(client, tmp_repo):
    """Brand + source + one completed parent run for official_site."""
    brand = client.post("/api/brands", json={"name": "EnrichCo"}).json()
    src = client.post(
        f"/api/brands/{brand['id']}/sources",
        json={
            "platform": "official_site",
            "spec": {
                "brand_url": "https://enrichco.test",
                "section": "mens",
                "categories": ["shoes"],
                "max_products": 2,
            },
        },
    ).json()
    run_id = "20260424T100000Z"
    runs_dir = tmp_repo._runs_dir(brand["id"], src["id"])
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(json.dumps({
        "_status": "ok",
        "_meta": {"platform": "official_site"},
        "records": [
            {
                "product_name": "Alpha",
                "product_url": "https://enrichco.test/p/alpha",
                "scraped_at": "2026-04-24T10:00:00Z",
            },
            {
                "product_name": "Beta",
                "product_url": "https://enrichco.test/p/beta",
                "scraped_at": "2026-04-24T10:00:00Z",
            },
        ],
    }))
    return {
        "brand_id": brand["id"],
        "source_id": src["id"],
        "run_id": run_id,
        "runs_dir": runs_dir,
    }


class FakeExtractor:
    """Drop-in for an EnrichmentExtractor. Deterministic rows; no browser."""
    platform_key = "official_site"
    available_fields = [
        FieldDef(id="description", label="Description", type="str", description="Main copy"),
    ]
    supports_freeform = True

    async def stream_enrichments(
        self, records, requested, ctx: ScrapeContext,
    ) -> AsyncIterator[EnrichmentRow]:
        # Mirror real extractors: skip records whose identity returns None
        # so ``products_skipped_no_key`` is computed consistently.
        from app.platforms.official_site_enrichment import OfficialSiteProductIdentity
        ident = OfficialSiteProductIdentity()
        for rec in records:
            pk = ident.product_key(rec)
            if pk is None:
                continue
            url = rec.product_url if hasattr(rec, "product_url") else rec.get("product_url")
            yield EnrichmentRow(
                product_key=pk,
                values={"description": f"desc for {url}"},
                errors={},
                enriched_at=datetime.now(timezone.utc),
            )


class FailingExtractor(FakeExtractor):
    """Extractor whose rows all carry an error — exercises 'failed' aggregate."""

    async def stream_enrichments(self, records, requested, ctx: ScrapeContext):
        for rec in records:
            url = rec.product_url if hasattr(rec, "product_url") else rec.get("product_url")
            yield EnrichmentRow(
                product_key=url or "unknown",
                values={},
                errors={"_all": "RuntimeError: simulated"},
                enriched_at=datetime.now(timezone.utc),
            )


@pytest.fixture
def stub_runner_in_main(monkeypatch):
    """Replace ``app.main.run_enrichment`` so endpoint tests don't spawn
    real background tasks that would race the TestClient event loop."""
    async def _noop(session):
        return None
    monkeypatch.setattr(app_main, "run_enrichment", _noop)


@pytest.fixture
def use_fake_extractor(monkeypatch):
    """Plug a fake extractor into the runner registry for run_enrichment tests."""
    monkeypatch.setitem(runner.ENRICHMENT_EXTRACTORS, "official_site", FakeExtractor)


# --- GET /platforms/{platform}/enrichment_fields ----------------------------


def test_get_enrichment_fields_official_site(client):
    r = client.get("/api/platforms/official_site/enrichment_fields")
    assert r.status_code == 200
    data = r.json()
    assert data["supports_freeform"] is True
    assert "description" in {f["id"] for f in data["fields"]}


def test_get_enrichment_fields_shopee_has_freeform_false(client):
    r = client.get("/api/platforms/shopee/enrichment_fields")
    assert r.status_code == 200
    assert r.json()["supports_freeform"] is False


def test_get_enrichment_fields_unknown_platform(client):
    assert client.get("/api/platforms/bogus/enrichment_fields").status_code == 404


# --- POST /enrichments (endpoint layer) -------------------------------------


def test_post_enrichment_endpoint_accepts_and_returns_session_id(
    client, seeded, stub_runner_in_main,
):
    r = client.post(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments",
        json={"curated_fields": ["description"], "freeform_prompts": []},
    )
    assert r.status_code == 200
    session_id = r.json()["session_id"]
    assert session_id
    # Session registered, ready for the SSE/cancel endpoints to target.
    assert session_id in sessions


def test_post_enrichment_rejects_unknown_curated_field(client, seeded):
    r = client.post(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments",
        json={"curated_fields": ["not_a_field"], "freeform_prompts": []},
    )
    assert r.status_code == 422
    assert "not_a_field" in r.json()["detail"]


def test_post_enrichment_rejects_freeform_on_shopee(client, tmp_repo):
    brand = client.post("/api/brands", json={"name": "ShopeeCo"}).json()
    src = client.post(
        f"/api/brands/{brand['id']}/sources",
        json={"platform": "shopee", "spec": {"shop_url": "https://shopee.sg/x", "max_products": 1}},
    ).json()
    run_id = "20260424T110000Z"
    runs_dir = tmp_repo._runs_dir(brand["id"], src["id"])
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(json.dumps({
        "_status": "ok", "_meta": {"platform": "shopee"}, "records": [],
    }))
    r = client.post(
        f"/api/brands/{brand['id']}/sources/{src['id']}/runs/{run_id}/enrichments",
        json={
            "curated_fields": ["description"],
            "freeform_prompts": [{"id": "is_vegan", "label": "vegan?", "prompt": "Is vegan?"}],
        },
    )
    assert r.status_code == 422
    assert "freeform" in r.json()["detail"]


def test_post_enrichment_rejects_in_progress_parent(client, seeded):
    (seeded["runs_dir"] / f"{seeded['run_id']}.json").unlink()
    (seeded["runs_dir"] / f"{seeded['run_id']}.partial.json").write_text(json.dumps({
        "_status": "in_progress",
        "_meta": {"platform": "official_site"},
        "records": [],
    }))
    r = client.post(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments",
        json={"curated_fields": ["description"], "freeform_prompts": []},
    )
    assert r.status_code == 409


def test_post_enrichment_allows_cancelled_parent(client, seeded, stub_runner_in_main):
    (seeded["runs_dir"] / f"{seeded['run_id']}.json").unlink()
    (seeded["runs_dir"] / f"{seeded['run_id']}.partial.json").write_text(json.dumps({
        "_status": "cancelled",
        "_meta": {"platform": "official_site"},
        "records": [],
    }))
    r = client.post(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments",
        json={"curated_fields": ["description"], "freeform_prompts": []},
    )
    assert r.status_code == 200


def test_post_enrichment_rejects_missing_parent(client, seeded):
    r = client.post(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/nope/enrichments",
        json={"curated_fields": ["description"], "freeform_prompts": []},
    )
    assert r.status_code == 404


def test_post_enrichment_mutex_against_other_session(client, seeded, stub_runner_in_main):
    r1 = client.post(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments",
        json={"curated_fields": ["description"], "freeform_prompts": []},
    )
    assert r1.status_code == 200
    r2 = client.post(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments",
        json={"curated_fields": ["description"], "freeform_prompts": []},
    )
    assert r2.status_code == 409


def test_post_enrichment_validator_rejects_empty_request(client, seeded):
    # EnrichmentRequest's own validator forbids empty requests; surfaces
    # as 422 at the endpoint boundary.
    r = client.post(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments",
        json={"curated_fields": [], "freeform_prompts": []},
    )
    assert r.status_code == 422


# --- GET / DELETE enrichments (file-based, no runner needed) ----------------


def _write_enrichment(runs_dir, run_id, enr_id, *, status="ok", aggregates=None, results=None):
    edir = runs_dir / f"{run_id}{ENRICHMENT_DIR_SUFFIX}"
    edir.mkdir(exist_ok=True)
    payload = {
        "_status": status,
        "_meta": {
            "parent_run_id": run_id,
            "started_at": enr_id,
            "request": {"curated_fields": ["description"], "freeform_prompts": []},
            "aggregates": aggregates or {},
        },
        "results": results or [],
    }
    suffix = ".partial.json" if status == "in_progress" else ".json"
    (edir / f"{enr_id}{suffix}").write_text(json.dumps(payload))


def test_list_enrichments_endpoint(client, seeded):
    _write_enrichment(
        seeded["runs_dir"], seeded["run_id"], "20260424T120000Z-aaaa",
        aggregates={"products_enriched": 2},
    )
    r = client.get(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments"
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["aggregates"]["products_enriched"] == 2


def test_list_enrichments_404_for_missing_run(client, seeded):
    r = client.get(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}/runs/nope/enrichments"
    )
    assert r.status_code == 404


def test_get_enrichment_returns_full_payload(client, seeded):
    _write_enrichment(
        seeded["runs_dir"], seeded["run_id"], "eid1",
        results=[{
            "product_key": "x", "values": {"description": "hi"},
            "errors": {}, "enriched_at": "2026-04-24T12:00:00Z",
        }],
    )
    r = client.get(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments/eid1"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["_status"] == "ok"
    assert body["results"][0]["product_key"] == "x"


def test_delete_enrichment_endpoint(client, seeded):
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "eid1")
    r = client.delete(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments/eid1"
    )
    assert r.status_code == 204
    edir = seeded["runs_dir"] / f"{seeded['run_id']}{ENRICHMENT_DIR_SUFFIX}"
    assert not (edir / "eid1.json").exists()


def test_delete_enrichment_missing_returns_404(client, seeded):
    r = client.delete(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments/nope"
    )
    assert r.status_code == 404


def test_delete_enrichment_blocked_by_active_session(client, seeded, stub_runner_in_main):
    # Start an enrichment, leaving a session registered.
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "eid1")
    r = client.post(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments",
        json={"curated_fields": ["description"], "freeform_prompts": []},
    )
    assert r.status_code == 200

    resp = client.delete(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/enrichments/eid1"
    )
    assert resp.status_code == 409


def test_delete_run_cascades_to_enrichment_dir(client, seeded):
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "eid1")
    resp = client.delete(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}"
    )
    assert resp.status_code == 204
    assert not (seeded["runs_dir"] / f"{seeded['run_id']}{ENRICHMENT_DIR_SUFFIX}").exists()


# --- GET /table --------------------------------------------------------------


def test_unified_table_endpoint_joins(client, seeded):
    _write_enrichment(
        seeded["runs_dir"], seeded["run_id"], "eid1",
        results=[{
            "product_key": "https://enrichco.test/p/alpha",
            "values": {"description": "nice"},
            "errors": {},
            "enriched_at": "2026-04-24T12:00:00Z",
        }],
    )
    r = client.get(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/table"
    )
    assert r.status_code == 200
    body = r.json()
    col_ids = {c["id"] for c in body["columns"]}
    assert "product_name" in col_ids
    assert "description" in col_ids
    alpha = next(
        row for row in body["rows"]
        if row["product_key"] == "https://enrichco.test/p/alpha"
    )
    assert alpha["description"] == "nice"


def test_unified_table_endpoint_rejects_empty_include(client, seeded):
    r = client.get(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}"
        f"/runs/{seeded['run_id']}/table?include_enrichments="
    )
    assert r.status_code == 422


def test_unified_table_endpoint_missing_run(client, seeded):
    r = client.get(
        f"/api/brands/{seeded['brand_id']}/sources/{seeded['source_id']}/runs/nope/table"
    )
    assert r.status_code == 404


# --- run_enrichment direct tests --------------------------------------------


def _make_session(seeded_dict, *, curated=("description",), freeform=()) -> ScrapeSession:
    from app.models import FreeformPrompt
    return ScrapeSession(
        id="sess",
        brand_id=seeded_dict["brand_id"],
        source_id=seeded_dict["source_id"],
        parent_run_id=seeded_dict["run_id"],
        request=EnrichmentRequest(
            curated_fields=list(curated),
            freeform_prompts=[FreeformPrompt(**fp) for fp in freeform],
        ),
    )


async def _drive(session: ScrapeSession, coro_fn):
    """Run ``coro_fn(session)`` while draining the queue so the partial
    flush and done/error/cancelled events all land before we assert."""
    events: list[dict[str, Any]] = []

    async def drain():
        while True:
            evt = await session.queue.get()
            events.append(evt)
            if evt["event"] in {"done", "error", "cancelled"}:
                return

    task = asyncio.create_task(coro_fn(session))
    await drain()
    await task
    return events


def test_run_enrichment_happy_path_emits_and_persists(seeded, use_fake_extractor):
    session = _make_session(seeded)
    events = asyncio.run(_drive(session, run_enrichment))
    names = [e["event"] for e in events]
    assert names[0] == "enrichment_started"
    assert names[-1] == "done"
    row_events = [e for e in events if e["event"] == "enrichment_row"]
    assert len(row_events) == 2
    for i, e in enumerate(row_events, start=1):
        data = json.loads(e["data"])
        assert data["index"] == i
        assert data["total"] == 2
        assert data["values"]["description"].startswith("desc for ")

    edir = seeded["runs_dir"] / f"{seeded['run_id']}{ENRICHMENT_DIR_SUFFIX}"
    finals = list(edir.glob("*.json"))
    assert len(finals) == 1
    payload = json.loads(finals[0].read_text())
    assert payload["_status"] == "ok"
    assert payload["_meta"]["aggregates"] == {
        "products_attempted": 2,
        "products_enriched": 2,
        "products_failed": 0,
        "products_skipped_no_key": 0,
        "products_skipped_already_enriched": 0,
    }
    assert payload["_meta"]["parent_run_id"] == seeded["run_id"]
    assert payload["_meta"]["platform"] == "official_site"


def test_run_enrichment_counts_failed_rows(seeded, monkeypatch):
    monkeypatch.setitem(runner.ENRICHMENT_EXTRACTORS, "official_site", FailingExtractor)
    session = _make_session(seeded)
    events = asyncio.run(_drive(session, run_enrichment))
    assert events[-1]["event"] == "done"

    edir = seeded["runs_dir"] / f"{seeded['run_id']}{ENRICHMENT_DIR_SUFFIX}"
    payload = json.loads(list(edir.glob("*.json"))[0].read_text())
    assert payload["_meta"]["aggregates"]["products_failed"] == 2
    assert payload["_meta"]["aggregates"]["products_enriched"] == 0


def test_run_enrichment_counts_skipped_records_without_key(
    seeded, tmp_repo, use_fake_extractor,
):
    # Rewrite the parent so one record has no product_url → skipped by the
    # official_site identity.
    (seeded["runs_dir"] / f"{seeded['run_id']}.json").write_text(json.dumps({
        "_status": "ok",
        "_meta": {"platform": "official_site"},
        "records": [
            {"product_name": "A", "product_url": None, "scraped_at": "2026-04-24T10:00:00Z"},
            {"product_name": "B", "product_url": "https://enrichco.test/b",
             "scraped_at": "2026-04-24T10:00:00Z"},
        ],
    }))
    session = _make_session(seeded)
    asyncio.run(_drive(session, run_enrichment))
    edir = seeded["runs_dir"] / f"{seeded['run_id']}{ENRICHMENT_DIR_SUFFIX}"
    payload = json.loads(list(edir.glob("*.json"))[0].read_text())
    aggs = payload["_meta"]["aggregates"]
    assert aggs["products_skipped_no_key"] == 1
    assert aggs["products_attempted"] == 1


def test_run_enrichment_skips_already_enriched_products(
    seeded, tmp_repo, use_fake_extractor,
):
    """If a previous enrichment pass already populated all requested fields
    for some products, the runner pre-filters them so the extractor never
    sees them, and the count surfaces in aggregates + the started banner."""
    # Seed an existing enrichment pass that populated `description` for the
    # alpha product but not beta.
    edir = seeded["runs_dir"] / f"{seeded['run_id']}{ENRICHMENT_DIR_SUFFIX}"
    edir.mkdir(parents=True, exist_ok=True)
    (edir / "prior.json").write_text(json.dumps({
        "_status": "ok",
        "_meta": {"platform": "official_site"},
        "results": [
            {
                "product_key": "https://enrichco.test/p/alpha",
                "values": {"description": "already done"},
                "errors": {},
            },
        ],
    }))

    # Capture what the extractor actually sees.
    seen_records: list[Any] = []

    class CapturingExtractor(FakeExtractor):
        async def stream_enrichments(self, records, requested, ctx):
            seen_records.extend(records)
            async for row in FakeExtractor().stream_enrichments(records, requested, ctx):
                yield row

    import app.runner as runner_mod
    runner_mod.ENRICHMENT_EXTRACTORS["official_site"] = CapturingExtractor
    try:
        session = _make_session(seeded)
        events = asyncio.run(_drive(session, run_enrichment))
    finally:
        runner_mod.ENRICHMENT_EXTRACTORS["official_site"] = FakeExtractor

    # Extractor was called with only the un-enriched record (beta).
    assert len(seen_records) == 1
    rec = seen_records[0]
    url = rec.product_url if hasattr(rec, "product_url") else rec["product_url"]
    assert url == "https://enrichco.test/p/beta"

    # `enrichment_started` banner reflects the skip.
    started = next(e for e in events if e["event"] == "enrichment_started")
    started_data = json.loads(started["data"])
    assert started_data["products_skipped_already_enriched"] == 1
    assert started_data["total_products"] == 2
    assert started_data["products_skipped_no_key"] == 0

    # The new enrichment file's aggregates carry the new key.
    finals = sorted(p for p in edir.glob("*.json") if p.name != "prior.json")
    assert len(finals) == 1
    payload = json.loads(finals[0].read_text())
    aggs = payload["_meta"]["aggregates"]
    assert aggs["products_skipped_already_enriched"] == 1
    assert aggs["products_attempted"] == 1
    assert aggs["products_enriched"] == 1


def test_run_enrichment_bails_on_missing_parent_run(seeded, use_fake_extractor):
    session = _make_session(seeded)
    session.parent_run_id = "does-not-exist"
    events = asyncio.run(_drive(session, run_enrichment))
    assert events[-1]["event"] == "error"
    assert "not found" in json.loads(events[-1]["data"])["message"]


def test_run_enrichment_bails_on_in_progress_parent(seeded, use_fake_extractor):
    (seeded["runs_dir"] / f"{seeded['run_id']}.json").write_text(json.dumps({
        "_status": "in_progress",
        "_meta": {"platform": "official_site"},
        "records": [],
    }))
    session = _make_session(seeded)
    events = asyncio.run(_drive(session, run_enrichment))
    assert events[-1]["event"] == "error"
    assert "in_progress" in json.loads(events[-1]["data"])["message"]


def test_run_enrichment_cancel_event_stops_stream(seeded, use_fake_extractor):
    session = _make_session(seeded)
    session.cancel_event.set()  # cancel before any iteration
    events = asyncio.run(_drive(session, run_enrichment))
    names = [e["event"] for e in events]
    # started → (no rows) → cancelled. The extractor yields nothing because
    # its first cancel-check returns immediately.
    assert "enrichment_started" in names
    assert names[-1] == "cancelled"
    # Partial file is persisted with the cancelled status.
    edir = seeded["runs_dir"] / f"{seeded['run_id']}{ENRICHMENT_DIR_SUFFIX}"
    partials = list(edir.glob("*.partial.json"))
    assert len(partials) == 1
    payload = json.loads(partials[0].read_text())
    assert payload["_status"] == "cancelled"


# --- runner-level log capture ------------------------------------------------


class LoggingExtractor:
    """Extractor that emits an app.* log record per product to verify that
    runner-level attach now captures app-logger records into the sidecar."""
    platform_key = "official_site"
    available_fields = [
        FieldDef(id="description", label="Description", type="str", description="x"),
    ]
    supports_freeform = True

    async def stream_enrichments(self, records, requested, ctx):
        from app.platforms.official_site_enrichment import OfficialSiteProductIdentity
        ident = OfficialSiteProductIdentity()
        log = _logging.getLogger("app.test_logging_extractor")
        for rec in records:
            pk = ident.product_key(rec)
            if pk is None:
                continue
            log.warning("probe: enriching %s", pk)
            yield EnrichmentRow(
                product_key=pk,
                values={"description": "ok"},
                errors={},
                enriched_at=datetime.now(timezone.utc),
            )


def test_run_enrichment_sidecar_captures_app_logger_warnings(
    seeded, monkeypatch,
):
    monkeypatch.setitem(runner.ENRICHMENT_EXTRACTORS, "official_site", LoggingExtractor)
    session = _make_session(seeded)
    asyncio.run(_drive(session, run_enrichment))

    edir = seeded["runs_dir"] / f"{seeded['run_id']}{ENRICHMENT_DIR_SUFFIX}"
    log_files = list(edir.glob("*.log.jsonl"))
    assert len(log_files) == 1, f"expected 1 log file, got {log_files}"
    lines = [
        json.loads(l) for l in log_files[0].read_text().splitlines() if l.strip()
    ]
    assert any(
        "probe: enriching" in entry["message"] and entry["level"] == "warning"
        for entry in lines
    ), f"log file did not contain expected warning; got: {lines}"


def test_run_job_detaches_handlers_after_completion(seeded, use_fake_extractor):
    """Regression for handler-leak: after a pass finishes, the captured
    loggers should have no QueueLogHandler left attached."""
    session = _make_session(seeded)
    asyncio.run(_drive(session, run_enrichment))

    from app.session import QueueLogHandler
    for name in _CAPTURED_LOGGERS:
        dangling = [
            h for h in _logging.getLogger(name).handlers
            if isinstance(h, QueueLogHandler)
        ]
        assert dangling == [], f"{name} has leaked QueueLogHandler(s): {dangling}"
