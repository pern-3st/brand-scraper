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
    OfficialSiteProductRecord,
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
    rec = OfficialSiteProductRecord(
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
    """Stub launch_persistent_context + extract_structured_from_page +
    build_llm so tests run without launching Chrome or hitting an LLM."""
    from contextlib import asynccontextmanager

    calls: dict[str, Any] = {"navigations": [], "extracts": []}

    class _StubPage:
        async def goto(self, url, **_kw):
            calls["navigations"].append(url)
        async def evaluate(self, *_a, **_kw):
            return ""

    class _StubContext:
        async def new_page(self):
            return _StubPage()
        async def close(self):
            pass

    @asynccontextmanager
    async def _fake_launch():
        yield None, _StubContext()

    monkeypatch.setattr(ose, "launch_persistent_context", _fake_launch)
    monkeypatch.setattr(ose, "build_llm", lambda: object())

    # Skip the 8-20s jitter sleep between products + the post-goto settle
    # so tests stay fast. The dedicated pacing test re-monkeypatches this
    # to record the call args.
    async def _fast_pace_sleep(seconds: float, cancel_event):
        return cancel_event.is_set()

    monkeypatch.setattr(ose, "_pace_sleep", _fast_pace_sleep)

    # Skip the warmup idle so existing tests don't have to model it.
    async def _fast_warmup_idle(_page, cancel_event):
        return cancel_event.is_set()

    monkeypatch.setattr(ose, "_warmup_idle", _fast_warmup_idle)
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
    async def fake_extract(page, *, llm, schema, query):
        # Return a schema instance with both curated (description) and freeform (is_vegan).
        return schema(description="A soft tee", is_vegan="Yes")

    monkeypatch.setattr(ose, "extract_structured_from_page", fake_extract)

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
    # First navigation is the warmup URL (brand homepage); the next two are
    # the product URLs in order.
    assert mocked_browser["navigations"] == [
        "https://brand.com/",
        "https://brand.com/a",
        "https://brand.com/b",
    ]


def test_stream_enrichments_records_per_product_failures(mocked_browser, monkeypatch):
    counter = {"n": 0}

    async def fake_extract(page, *, llm, schema, query):
        counter["n"] += 1
        if counter["n"] == 2:
            raise RuntimeError("simulated extract failure")
        return schema(description="ok")

    monkeypatch.setattr(ose, "extract_structured_from_page", fake_extract)

    req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    records = [_rec(f"https://brand.com/p{i}") for i in range(3)]
    rows = asyncio.run(_drain(ose.OfficialSiteEnrichment(), records, req))

    # All three products surface a row; the middle one carries an error instead of values.
    assert len(rows) == 3
    assert rows[0].values["description"] == "ok" and rows[0].errors == {}
    assert rows[1].values == {} and "RuntimeError" in rows[1].errors["_all"]
    assert rows[2].values["description"] == "ok" and rows[2].errors == {}


def test_stream_enrichments_skips_records_without_url(mocked_browser, monkeypatch):
    async def fake_extract(page, *, llm, schema, query):
        return schema(description="ok")

    monkeypatch.setattr(ose, "extract_structured_from_page", fake_extract)

    req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    records = [_rec(None), _rec("https://brand.com/valid")]
    rows = asyncio.run(_drain(ose.OfficialSiteEnrichment(), records, req))

    # Only the valid URL produces a row; the None-URL record is silently skipped by the identity.
    assert len(rows) == 1
    assert rows[0].product_key == "https://brand.com/valid"


def test_stream_enrichments_records_extract_returning_none(mocked_browser, monkeypatch):
    async def fake_extract(page, *, llm, schema, query):
        return None  # extract_structured hard-failed

    monkeypatch.setattr(ose, "extract_structured_from_page", fake_extract)

    req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    rows = asyncio.run(_drain(ose.OfficialSiteEnrichment(), [_rec("https://brand.com/a")], req))
    assert len(rows) == 1
    assert rows[0].values == {}
    assert "no data" in rows[0].errors["_all"]


def test_stream_enrichments_honours_cancel(mocked_browser, monkeypatch):
    async def fake_extract(page, *, llm, schema, query):
        return schema(description="ok")

    monkeypatch.setattr(ose, "extract_structured_from_page", fake_extract)

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
    async def fake_extract(page, *, llm, schema, query):
        return schema(description="ok")

    monkeypatch.setattr(ose, "extract_structured_from_page", fake_extract)

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
    # Inter-product sleeps fall in the [_PACE_MIN, _PACE_MAX] window; the
    # post-goto settle sleeps fall in [_POST_GOTO_SETTLE_MIN, _POST_GOTO_SETTLE_MAX].
    # Filter to inter-product pacing — there should be 3 of those (between 4
    # processed products), and 4 settle sleeps.
    inter_product_calls = [
        d for d in pace_calls
        if ose._PACE_MIN_SECONDS <= d <= ose._PACE_MAX_SECONDS
    ]
    settle_calls = [
        d for d in pace_calls
        if ose._POST_GOTO_SETTLE_MIN_SECONDS <= d <= ose._POST_GOTO_SETTLE_MAX_SECONDS
    ]
    assert len(inter_product_calls) == 3
    assert len(settle_calls) == 4


# --- build_browser_profile (persistent user_data_dir) ----------------------


def test_build_browser_profile_uses_persistent_user_data_dir(tmp_path, monkeypatch):
    from app.platforms import _browser_use

    monkeypatch.setattr(
        _browser_use,
        "OFFICIAL_SITE_PROFILE_DIR",
        tmp_path / "browser-use-user-data-dir-official_site",
    )
    profile = _browser_use.build_browser_profile()
    assert profile.user_data_dir is not None
    udir = Path(profile.user_data_dir)
    assert udir.exists()
    assert udir.is_dir()
    assert tmp_path in udir.parents


def test_build_browser_profile_reuses_same_dir_across_calls(tmp_path, monkeypatch):
    from app.platforms import _browser_use

    monkeypatch.setattr(
        _browser_use,
        "OFFICIAL_SITE_PROFILE_DIR",
        tmp_path / "browser-use-user-data-dir-official_site",
    )
    p1 = _browser_use.build_browser_profile()
    p2 = _browser_use.build_browser_profile()
    assert p1.user_data_dir == p2.user_data_dir


# --- Warmup URL derivation -------------------------------------------------


def test_derive_warmup_url_with_locale_segment():
    from app.platforms.official_site_enrichment import _derive_warmup_url
    assert _derive_warmup_url(
        "https://www2.hm.com/en_sg/productpage.1209140021.html"
    ) == "https://www2.hm.com/en_sg/"


def test_derive_warmup_url_without_locale_segment():
    from app.platforms.official_site_enrichment import _derive_warmup_url
    assert _derive_warmup_url("https://acme.test/p/123") == "https://acme.test/"


def test_derive_warmup_url_returns_none_for_garbage():
    from app.platforms.official_site_enrichment import _derive_warmup_url
    assert _derive_warmup_url("not a url") is None
    assert _derive_warmup_url("") is None
    assert _derive_warmup_url(None) is None


# --- Patchright session integration ----------------------------------------


@pytest.mark.asyncio
async def test_stream_enrichments_uses_patchright_session(monkeypatch):
    """Wires through patchright's launch_persistent_context and the new
    LLM-extract helper, yielding EnrichmentRow per processed product."""
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone

    visited_urls: list[str] = []

    class _FakePage:
        async def goto(self, url, **kwargs):
            visited_urls.append(url)
        async def evaluate(self, *args, **kwargs):
            return None

    class _FakeContext:
        async def new_page(self):
            return _FakePage()
        async def close(self):
            pass

    @asynccontextmanager
    async def fake_launch():
        yield None, _FakeContext()

    monkeypatch.setattr(ose, "launch_persistent_context", fake_launch)
    async def fake_extract(page, *, llm, schema, query):
        return schema(description="x")
    monkeypatch.setattr(ose, "extract_structured_from_page", fake_extract)
    monkeypatch.setattr(ose, "build_llm", lambda: object())
    async def fake_pace(seconds, evt):
        return False
    monkeypatch.setattr(ose, "_pace_sleep", fake_pace)

    records = [
        OfficialSiteProductRecord(
            product_name=f"P{i}",
            product_url=f"https://acme.test/p/{i}",
            scraped_at=datetime.now(timezone.utc),
        )
        for i in range(3)
    ]
    request = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    ctx = ScrapeContext(
        cancel_event=asyncio.Event(),
        login_event=asyncio.Event(),
        queue=asyncio.Queue(),
    )

    extractor = ose.OfficialSiteEnrichment()
    rows = [r async for r in extractor.stream_enrichments(records, request, ctx)]

    assert len(rows) == 3
    assert all(r.values == {"description": "x"} for r in rows)
    assert visited_urls[-3:] == [
        "https://acme.test/p/0",
        "https://acme.test/p/1",
        "https://acme.test/p/2",
    ]


# --- Warmup integration ----------------------------------------------------


@pytest.mark.asyncio
async def test_stream_enrichments_warms_up_before_first_product(monkeypatch):
    """The first navigation should hit the derived warmup URL, not the
    first product URL."""
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone

    nav_log: list[str] = []

    class _FakePage:
        async def goto(self, url, **kwargs):
            nav_log.append(url)
        async def evaluate(self, *args, **kwargs):
            return ""
        mouse = type("M", (), {"wheel": staticmethod(lambda *a, **k: _noop())})()

    async def _noop():
        return None

    class _FakeContext:
        async def new_page(self):
            return _FakePage()
        async def close(self):
            pass

    @asynccontextmanager
    async def fake_launch():
        yield None, _FakeContext()

    monkeypatch.setattr(ose, "launch_persistent_context", fake_launch)
    async def fake_extract(page, *, llm, schema, query):
        return schema(description="x")
    monkeypatch.setattr(ose, "extract_structured_from_page", fake_extract)
    monkeypatch.setattr(ose, "build_llm", lambda: object())
    async def fake_pace(seconds, evt):
        return False
    monkeypatch.setattr(ose, "_pace_sleep", fake_pace)
    async def fake_warmup_idle(page, evt):
        return False
    monkeypatch.setattr(ose, "_warmup_idle", fake_warmup_idle)

    records = [
        OfficialSiteProductRecord(
            product_name="P1",
            product_url="https://www2.hm.com/en_sg/productpage.1209140021.html",
            scraped_at=datetime.now(timezone.utc),
        ),
    ]
    request = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    ctx = ScrapeContext(
        cancel_event=asyncio.Event(),
        login_event=asyncio.Event(),
        queue=asyncio.Queue(),
    )

    extractor = ose.OfficialSiteEnrichment()
    [_ async for _ in extractor.stream_enrichments(records, request, ctx)]

    assert nav_log[0] == "https://www2.hm.com/en_sg/"
    assert nav_log[1] == "https://www2.hm.com/en_sg/productpage.1209140021.html"


# --- Block detection -------------------------------------------------------


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ("Access Denied\n\nYou don't have permission to access ...", True),
        ("Some normal page\nReference #18.a4a4c117.1777875665", True),
        ("Reference page about edgesuite.net domain", True),
        ("Product Title\n\nA cosy sweater in soft cotton.", False),
        ("", False),
    ],
)
@pytest.mark.asyncio
async def test_looks_like_block_string_markers(snippet, expected):
    from app.platforms.official_site_enrichment import _looks_like_block

    class _Page:
        async def evaluate(self, _):
            return snippet

    assert await _looks_like_block(_Page()) is expected


@pytest.mark.asyncio
async def test_looks_like_block_returns_false_when_evaluate_errors():
    """A failing evaluate (e.g. page detached during read) must NOT be
    treated as a block — the cost of a false positive is aborting an entire
    enrichment pass over a transient frame race."""
    from app.platforms.official_site_enrichment import _looks_like_block

    class _Page:
        async def evaluate(self, _):
            raise RuntimeError("page is detached")

    assert await _looks_like_block(_Page()) is False


@pytest.mark.asyncio
async def test_stream_enrichments_aborts_on_akamai_block(monkeypatch):
    """When a navigated page looks blocked, yield one error row and stop —
    don't continue hammering subsequent products."""
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone

    class _FakePage:
        def __init__(self):
            self._last = ""
        async def goto(self, url, **kwargs):
            self._last = url
        async def evaluate(self, _):
            # Block on the second product's nav.
            if "/p/2" in self._last:
                return "Access Denied\nReference #..."
            return "ok"

    class _FakeContext:
        async def new_page(self):
            return _FakePage()
        async def close(self):
            pass

    @asynccontextmanager
    async def fake_launch():
        yield None, _FakeContext()

    monkeypatch.setattr(ose, "launch_persistent_context", fake_launch)
    async def fake_extract(page, *, llm, schema, query):
        return schema(description="x")
    monkeypatch.setattr(ose, "extract_structured_from_page", fake_extract)
    monkeypatch.setattr(ose, "build_llm", lambda: object())
    async def fake_pace(seconds, evt):
        return False
    monkeypatch.setattr(ose, "_pace_sleep", fake_pace)
    async def fake_warmup_idle(page, evt):
        return False
    monkeypatch.setattr(ose, "_warmup_idle", fake_warmup_idle)
    # Skip warmup-URL nav by stubbing _derive_warmup_url to return None.
    monkeypatch.setattr(ose, "_derive_warmup_url", lambda _: None)

    records = [
        OfficialSiteProductRecord(
            product_name=f"P{i}",
            product_url=f"https://acme.test/p/{i}",
            scraped_at=datetime.now(timezone.utc),
        )
        for i in range(1, 5)  # /p/1 .. /p/4
    ]
    request = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    ctx = ScrapeContext(
        cancel_event=asyncio.Event(),
        login_event=asyncio.Event(),
        queue=asyncio.Queue(),
    )

    extractor = ose.OfficialSiteEnrichment()
    rows = [r async for r in extractor.stream_enrichments(records, request, ctx)]

    assert len(rows) == 2
    assert rows[0].values == {"description": "x"}
    assert rows[1].errors == {"_all": "akamai_block"}
    assert rows[1].values == {}


# --- Registry ---------------------------------------------------------------


def test_registered_in_runner_registries():
    from app import runner
    assert "official_site" in runner.ENRICHMENT_EXTRACTORS
    assert "official_site" in runner.PRODUCT_IDENTITIES
    assert isinstance(runner.PRODUCT_IDENTITIES["official_site"], ose.OfficialSiteProductIdentity)
