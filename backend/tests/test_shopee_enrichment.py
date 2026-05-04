"""Unit + integration tests for the Shopee enrichment extractor.

Stubs out the patchright persistent context, the login-wall recovery,
and the DOM extractor so tests run with no browser / network. What's
actually exercised: identity, field filtering, per-product failure
isolation, cancel, freeform rejection, registry wiring.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import pytest

from app.models import (
    EnrichmentRequest,
    FreeformPrompt,
    ProductRecord,
)
from app.platforms.base import ScrapeContext
from app.platforms.shopee import enrichment as se


# --- Identity --------------------------------------------------------------


def test_identity_uses_item_id_as_string():
    ident = se.ShopeeProductIdentity()
    assert ident.product_key({"item_id": 19823746}) == "19823746"


def test_identity_accepts_basemodel():
    ident = se.ShopeeProductIdentity()
    rec = ProductRecord(
        product_name="X",
        item_id=42,
        scraped_at=datetime.now(timezone.utc),
    )
    assert ident.product_key(rec) == "42"


def test_identity_returns_none_without_item_id():
    ident = se.ShopeeProductIdentity()
    assert ident.product_key({}) is None
    assert ident.product_key({"item_id": None}) is None


def test_identity_returns_none_for_malformed_item_id():
    ident = se.ShopeeProductIdentity()
    assert ident.product_key({"item_id": "not-a-number"}) is None


# --- Harness ---------------------------------------------------------------


@pytest.fixture
def mocked_shopee(monkeypatch):
    """Stub persistent-context launch + login-wall recovery so tests
    exercise ``stream_enrichments`` without touching Chrome or the network.
    """
    calls: dict[str, Any] = {
        "navigations": [],
        "extracts": 0,
        "logout_wall": False,
    }

    class FakePage:
        pass

    class FakeContext:
        async def new_page(self) -> FakePage:
            return FakePage()

    @asynccontextmanager
    async def fake_launch():
        yield (object(), FakeContext())

    async def fake_navigate(page, url, ctx, *, ready_selector=None, **kw):
        calls["navigations"].append(url)
        if ctx.cancel_event.is_set():
            return False
        return True

    monkeypatch.setattr(se, "launch_persistent_context", fake_launch)
    monkeypatch.setattr(se, "navigate_with_login_wall_recovery", fake_navigate)
    return calls


def _ctx() -> ScrapeContext:
    return ScrapeContext(
        cancel_event=asyncio.Event(),
        login_event=asyncio.Event(),
        queue=asyncio.Queue(),
    )


def _rec(item_id: int | None, url: str | None = "https://shopee.sg/p-i.1.2") -> dict[str, Any]:
    return {
        "product_name": "X",
        "product_url": url,
        "item_id": item_id,
        "scraped_at": "2026-04-24T10:00:00Z",
    }


async def _drain(ext, records, req):
    ctx = _ctx()
    out = []
    async for row in ext.stream_enrichments(records, req, ctx):
        out.append(row)
    return out


# --- stream_enrichments ----------------------------------------------------


def test_stream_enrichments_fills_requested_curated_fields(mocked_shopee, monkeypatch):
    async def fake_extract(page):
        return {
            "description": "A soft tee",
            "variant_options": ["S", "M", "L"],
            "shop_name": "BrandCo",
            "shop_rating": 4.8,
            "shop_follower_count": 12000,
            "rating_count": 42,
        }

    monkeypatch.setattr(se, "extract_product_fields", fake_extract)

    req = EnrichmentRequest(
        curated_fields=["description", "shop_rating"],
        freeform_prompts=[],
    )
    records = [
        _rec(1, "https://shopee.sg/a-i.1.1"),
        _rec(2, "https://shopee.sg/b-i.1.2"),
    ]

    rows = asyncio.run(_drain(se.ShopeeEnrichment(), records, req))

    assert [r.product_key for r in rows] == ["1", "2"]
    for r in rows:
        # Only the two requested fields surface — nothing else.
        assert set(r.values.keys()) == {"description", "shop_rating"}
        assert r.values["description"] == "A soft tee"
        assert r.values["shop_rating"] == 4.8
        assert r.errors == {}
    assert mocked_shopee["navigations"] == [
        "https://shopee.sg/a-i.1.1",
        "https://shopee.sg/b-i.1.2",
    ]


def test_stream_enrichments_marks_missing_fields_as_errors(mocked_shopee, monkeypatch):
    async def fake_extract(page):
        return {
            "description": "ok",
            "shop_rating": None,
            "rating_count": None,
        }

    monkeypatch.setattr(se, "extract_product_fields", fake_extract)

    req = EnrichmentRequest(
        curated_fields=["description", "shop_rating", "rating_count"],
        freeform_prompts=[],
    )
    rows = asyncio.run(_drain(se.ShopeeEnrichment(), [_rec(7)], req))
    assert len(rows) == 1
    r = rows[0]
    assert r.values == {"description": "ok"}
    assert "shop_rating" in r.errors
    assert "rating_count" in r.errors


def test_stream_enrichments_records_per_product_failures(mocked_shopee, monkeypatch):
    counter = {"n": 0}

    async def fake_extract(page):
        counter["n"] += 1
        if counter["n"] == 2:
            raise RuntimeError("simulated DOM failure")
        return {"description": "ok"}

    monkeypatch.setattr(se, "extract_product_fields", fake_extract)

    req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    records = [_rec(i) for i in range(1, 4)]
    rows = asyncio.run(_drain(se.ShopeeEnrichment(), records, req))

    assert len(rows) == 3
    assert rows[0].values == {"description": "ok"} and rows[0].errors == {}
    assert rows[1].values == {} and "RuntimeError" in rows[1].errors["_all"]
    assert rows[2].values == {"description": "ok"} and rows[2].errors == {}


def test_stream_enrichments_skips_records_without_item_id(mocked_shopee, monkeypatch):
    async def fake_extract(page):
        return {"description": "ok"}

    monkeypatch.setattr(se, "extract_product_fields", fake_extract)

    req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
    records = [_rec(None), _rec(5)]
    rows = asyncio.run(_drain(se.ShopeeEnrichment(), records, req))

    assert len(rows) == 1
    assert rows[0].product_key == "5"


def test_stream_enrichments_honours_cancel(mocked_shopee, monkeypatch):
    async def fake_extract(page):
        return {"description": "ok"}

    monkeypatch.setattr(se, "extract_product_fields", fake_extract)

    async def run_and_cancel():
        ext = se.ShopeeEnrichment()
        ctx = _ctx()
        ctx.cancel_event.set()
        req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
        out = []
        async for row in ext.stream_enrichments([_rec(1), _rec(2)], req, ctx):
            out.append(row)
        return out

    rows = asyncio.run(run_and_cancel())
    assert rows == []


def test_stream_enrichments_rejects_freeform_prompts(mocked_shopee):
    req = EnrichmentRequest(
        curated_fields=["description"],
        freeform_prompts=[FreeformPrompt(id="is_vegan", label="", prompt="Is vegan?")],
    )

    with pytest.raises(ValueError, match="freeform"):
        asyncio.run(_drain(se.ShopeeEnrichment(), [_rec(1)], req))


def test_stream_enrichments_rejects_request_with_no_known_fields(mocked_shopee):
    req = EnrichmentRequest(curated_fields=["not_in_catalog"], freeform_prompts=[])
    with pytest.raises(ValueError, match="no known curated fields"):
        asyncio.run(_drain(se.ShopeeEnrichment(), [_rec(1)], req))


# --- Catalog ----------------------------------------------------------------


def test_available_fields_are_all_valid_fielddefs():
    # Sanity: catalog entries pass the FieldDef identifier validator, so
    # request-validation / schema-build will accept them.
    ids = {fd.id for fd in se.ShopeeEnrichment().available_fields}
    assert ids == {
        "description", "variant_options", "shop_name",
        "shop_rating", "shop_follower_count", "rating_count",
    }


def test_supports_freeform_flag():
    assert se.ShopeeEnrichment.supports_freeform is False


# --- Registry ---------------------------------------------------------------


def test_registered_in_runner_registries():
    from app import runner
    assert runner.ENRICHMENT_EXTRACTORS["shopee"] is se.ShopeeEnrichment
    assert isinstance(runner.PRODUCT_IDENTITIES["shopee"], se.ShopeeProductIdentity)
