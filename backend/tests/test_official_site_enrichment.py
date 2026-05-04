"""Unit + integration tests for the official_site enrichment extractor."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.models import (
    EnrichmentRequest,
    FieldDef,
    FreeformPrompt,
    ProductRecord,
)
from app.platforms import official_site_enrichment as ose
from app.platforms.base import ScrapeContext


# --- Identity ---------------------------------------------------------------


def test_identity_uses_canonical_url():
    ident = ose.OfficialSiteProductIdentity()
    key = ident.product_key({"product_url": "https://Example.com/Foo/?utm=1"})
    assert key == "https://example.com/Foo"


def test_identity_accepts_basemodel():
    ident = ose.OfficialSiteProductIdentity()
    from datetime import datetime, timezone
    rec = ProductRecord(
        product_name="X",
        product_url="https://brand.com/p/123",
        scraped_at=datetime.now(timezone.utc),
    )
    assert ident.product_key(rec) == "https://brand.com/p/123"


def test_identity_returns_none_without_url():
    ident = ose.OfficialSiteProductIdentity()
    assert ident.product_key({"product_url": None}) is None
    assert ident.product_key({}) is None
    assert ident.product_key({"product_url": ""}) is None


# --- Schema builder ---------------------------------------------------------


def test_build_schema_model_curated_only_types():
    curated = [
        FieldDef(id="description", label="", type="str", description="desc"),
        FieldDef(id="rating", label="", type="float", description="r"),
        FieldDef(id="rating_count", label="", type="int", description="rc"),
        FieldDef(id="in_stock", label="", type="bool", description="s"),
        FieldDef(id="variants", label="", type="list[str]", description="v"),
    ]
    model = ose.build_schema_model(curated=curated, freeform=[])
    # All fields nullable so the LLM can decline.
    instance = model()  # type: ignore[call-arg]
    for fid in ("description", "rating", "rating_count", "in_stock", "variants"):
        assert hasattr(instance, fid)
        assert getattr(instance, fid) is None


def test_build_schema_model_freeform_all_str_optional():
    freeform = [
        FreeformPrompt(id="is_vegan", label="", prompt="Does this contain animal products?"),
    ]
    model = ose.build_schema_model(curated=[], freeform=freeform)
    # Can assign a string or None — both valid.
    model(is_vegan="No")
    model(is_vegan=None)
    # Description on the field is populated so the LLM reads the prompt.
    schema = model.model_json_schema()
    assert "animal products" in schema["properties"]["is_vegan"]["description"]


def test_build_schema_model_accepts_typed_values():
    curated = [
        FieldDef(id="rating", label="", type="float", description="r"),
        FieldDef(id="variants", label="", type="list[str]", description="v"),
    ]
    model = ose.build_schema_model(curated=curated, freeform=[])
    inst = model(rating=4.2, variants=["S", "M", "L"])
    assert inst.rating == 4.2
    assert inst.variants == ["S", "M", "L"]


def test_build_schema_model_rejects_empty():
    with pytest.raises(ValueError):
        ose.build_schema_model(curated=[], freeform=[])


def test_build_schema_model_rejects_collision():
    curated = [FieldDef(id="is_vegan", label="", type="bool", description="")]
    freeform = [FreeformPrompt(id="is_vegan", label="", prompt="Is vegan?")]
    with pytest.raises(ValueError):
        ose.build_schema_model(curated=curated, freeform=freeform)


# --- stream_enrichments (integration with mocked extract) -------------------


@pytest.fixture
def mocked_browser(monkeypatch):
    """Stub BrowserSession + extract_structured + build_llm so tests run without
    a real browser / network."""
    calls: dict[str, Any] = {"navigations": [], "extracts": []}

    class StubBrowser:
        def __init__(self, *_a, **_kw): pass
        async def start(self) -> None:
            pass
        async def navigate_to(self, url: str) -> None:
            calls["navigations"].append(url)
        async def stop(self) -> None:
            pass
        def get_current_page(self):  # unused but keeps parity with real BrowserSession
            return None

    monkeypatch.setattr(ose, "BrowserSession", StubBrowser)
    monkeypatch.setattr(ose, "build_llm", lambda: object())

    # Skip the 8-20s jitter sleep between products so tests stay fast. The
    # dedicated pacing test re-monkeypatches this to record the call args.
    async def _fast_pace_sleep(seconds: float, cancel_event):
        return cancel_event.is_set()

    monkeypatch.setattr(ose, "_pace_sleep", _fast_pace_sleep)
    return calls


def _ctx() -> ScrapeContext:
    return ScrapeContext(
        cancel_event=asyncio.Event(),
        login_event=asyncio.Event(),
        queue=asyncio.Queue(),
    )


def _rec(url: str | None) -> dict[str, Any]:
    return {
        "product_name": "X",
        "product_url": url,
        "scraped_at": "2026-04-24T10:00:00Z",
    }


async def _drain(ext, records, req):
    ctx = _ctx()
    out = []
    async for row in ext.stream_enrichments(records, req, ctx):
        out.append(row)
    return out


def test_stream_enrichments_fills_curated_and_freeform(mocked_browser, monkeypatch):
    async def fake_extract(*, browser, llm, schema, query, **kw):
        # Return a schema instance with both curated (description) and freeform (is_vegan).
        return schema(description="A soft tee", is_vegan="Yes")

    monkeypatch.setattr(ose, "extract_structured", fake_extract)

    req = EnrichmentRequest(
        curated_fields=["description"],
        freeform_prompts=[FreeformPrompt(id="is_vegan", label="", prompt="Is vegan?")],
    )
    records = [_rec("https://brand.com/a"), _rec("https://brand.com/b")]

    rows = asyncio.run(_drain(ose.OfficialSiteEnrichment(), records, req))

    assert len(rows) == 2
    assert {r.product_key for r in rows} == {"https://brand.com/a", "https://brand.com/b"}
    for r in rows:
        assert r.values["description"] == "A soft tee"
        assert r.values["is_vegan"] == "Yes"
        assert r.errors == {}
    assert mocked_browser["navigations"] == ["https://brand.com/a", "https://brand.com/b"]


def test_stream_enrichments_records_per_product_failures(mocked_browser, monkeypatch):
    counter = {"n": 0}

    async def fake_extract(*, browser, llm, schema, query, **kw):
        counter["n"] += 1
        if counter["n"] == 2:
            raise RuntimeError("simulated extract failure")
        return schema(description="ok")

    monkeypatch.setattr(ose, "extract_structured", fake_extract)

    req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    records = [_rec(f"https://brand.com/p{i}") for i in range(3)]
    rows = asyncio.run(_drain(ose.OfficialSiteEnrichment(), records, req))

    # All three products surface a row; the middle one carries an error instead of values.
    assert len(rows) == 3
    assert rows[0].values["description"] == "ok" and rows[0].errors == {}
    assert rows[1].values == {} and "RuntimeError" in rows[1].errors["_all"]
    assert rows[2].values["description"] == "ok" and rows[2].errors == {}


def test_stream_enrichments_skips_records_without_url(mocked_browser, monkeypatch):
    async def fake_extract(*, browser, llm, schema, query, **kw):
        return schema(description="ok")

    monkeypatch.setattr(ose, "extract_structured", fake_extract)

    req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    records = [_rec(None), _rec("https://brand.com/valid")]
    rows = asyncio.run(_drain(ose.OfficialSiteEnrichment(), records, req))

    # Only the valid URL produces a row; the None-URL record is silently skipped by the identity.
    assert len(rows) == 1
    assert rows[0].product_key == "https://brand.com/valid"


def test_stream_enrichments_records_extract_returning_none(mocked_browser, monkeypatch):
    async def fake_extract(*, browser, llm, schema, query, **kw):
        return None  # extract_structured hard-failed

    monkeypatch.setattr(ose, "extract_structured", fake_extract)

    req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    rows = asyncio.run(_drain(ose.OfficialSiteEnrichment(), [_rec("https://brand.com/a")], req))
    assert len(rows) == 1
    assert rows[0].values == {}
    assert "no data" in rows[0].errors["_all"]


def test_stream_enrichments_honours_cancel(mocked_browser, monkeypatch):
    async def fake_extract(*, browser, llm, schema, query, **kw):
        return schema(description="ok")

    monkeypatch.setattr(ose, "extract_structured", fake_extract)

    req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    records = [_rec(f"https://brand.com/p{i}") for i in range(3)]

    async def run_and_cancel():
        ext = ose.OfficialSiteEnrichment()
        ctx = _ctx()
        ctx.cancel_event.set()  # cancel before the first iteration
        out = []
        async for row in ext.stream_enrichments(records, req, ctx):
            out.append(row)
        return out

    rows = asyncio.run(run_and_cancel())
    assert rows == []


# --- _pace_sleep -----------------------------------------------------------


@pytest.mark.asyncio
async def test_pace_sleep_returns_false_when_not_cancelled(monkeypatch):
    slept: list[float] = []

    async def fake_wait_for(awaitable, timeout):
        slept.append(timeout)
        # Drain the coroutine so we don't leak a "never awaited" warning.
        try:
            awaitable.close()
        except Exception:
            pass
        raise asyncio.TimeoutError

    monkeypatch.setattr(ose.asyncio, "wait_for", fake_wait_for)

    cancel = asyncio.Event()
    cancelled = await ose._pace_sleep(5.0, cancel)
    assert cancelled is False
    assert slept == [5.0]


@pytest.mark.asyncio
async def test_pace_sleep_returns_true_when_cancelled():
    cancel = asyncio.Event()
    cancel.set()
    cancelled = await ose._pace_sleep(60.0, cancel)
    assert cancelled is True


# --- pacing inside the loop -------------------------------------------------


@pytest.mark.asyncio
async def test_stream_enrichments_paces_between_products(mocked_browser, monkeypatch):
    """Sleep between processed products only (not before the first, not at all
    for product_key=None records)."""
    async def fake_extract(*, browser, llm, schema, query, **kw):
        return schema(description="ok")

    monkeypatch.setattr(ose, "extract_structured", fake_extract)

    pace_calls: list[float] = []

    async def fake_pace_sleep(seconds: float, cancel_event):
        pace_calls.append(seconds)
        return False

    monkeypatch.setattr(ose, "_pace_sleep", fake_pace_sleep)

    req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    # 4 valid records + 1 with no URL (skipped — should NOT contribute pacing).
    records = [_rec(f"https://brand.com/p{i}") for i in range(4)]
    records.insert(2, _rec(None))

    rows = await _drain(ose.OfficialSiteEnrichment(), records, req)

    assert len(rows) == 4  # 4 processed; the None-URL record is silently skipped
    # 3 sleeps between 4 processed products; the no-URL record contributes none.
    assert len(pace_calls) == 3
    for delay in pace_calls:
        assert ose._PACE_MIN_SECONDS <= delay <= ose._PACE_MAX_SECONDS


# --- build_browser_profile (persistent user_data_dir) ----------------------


def test_build_browser_profile_uses_persistent_user_data_dir(tmp_path, monkeypatch):
    from app.platforms import _browser_use

    monkeypatch.setattr(_browser_use, "DATA_ROOT", tmp_path / "brands")
    profile = _browser_use.build_browser_profile()
    assert profile.user_data_dir is not None
    udir = Path(profile.user_data_dir)
    assert udir.exists()
    assert udir.is_dir()
    assert tmp_path in udir.parents


def test_build_browser_profile_reuses_same_dir_across_calls(tmp_path, monkeypatch):
    from app.platforms import _browser_use

    monkeypatch.setattr(_browser_use, "DATA_ROOT", tmp_path / "brands")
    p1 = _browser_use.build_browser_profile()
    p2 = _browser_use.build_browser_profile()
    assert p1.user_data_dir == p2.user_data_dir


# --- Registry ---------------------------------------------------------------


def test_registered_in_runner_registries():
    from app import runner
    assert "official_site" in runner.ENRICHMENT_EXTRACTORS
    assert "official_site" in runner.PRODUCT_IDENTITIES
    assert isinstance(runner.PRODUCT_IDENTITIES["official_site"], ose.OfficialSiteProductIdentity)
