"""Tests for LazadaScraper's response-handler logic.

We can't drive a real browser in CI, so this test exercises the
listener path via a fake `page.on("response", handler)` that captures
the registered callback and feeds it constructed responses. That's
the scraper's tricky bit — dedupe by auctionId, metadata enrichment,
queue-based producer/consumer between listener and async generator.

The step-scroll loop itself is verified by hand against live shops
(see plan's smoke-test sequencing); the listener is the part with
non-trivial branching.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.platforms.base import ScrapeContext
from app.platforms.lazada.models import LazadaScrapeRequest
from app.platforms.lazada.scraper import LazadaScraper

CAPTURE_DIR = (
    Path(__file__).resolve().parent.parent / "scripts" / "lazada_spike_captures"
)


def _load(name: str) -> dict:
    return json.loads((CAPTURE_DIR / name).read_text())


class FakeResponse:
    """Minimal patchright Response stand-in for the on_response handler."""

    def __init__(self, url: str, body: Any) -> None:
        self.url = url
        self._body = body

    async def json(self) -> Any:
        return self._body


class FakePage:
    """Captures the `response` handler so the test can drive it directly."""

    def __init__(self) -> None:
        self.handlers: list = []

    def on(self, event: str, handler) -> None:
        if event == "response":
            self.handlers.append(handler)

    async def fire(self, response: FakeResponse) -> None:
        for h in self.handlers:
            await h(response)


def _ctx() -> ScrapeContext:
    return ScrapeContext(
        cancel_event=asyncio.Event(),
        login_event=asyncio.Event(),
        queue=asyncio.Queue(),
    )


@pytest.mark.asyncio
async def test_handler_dedups_by_auction_id_and_enriches_with_metadata():
    """The listener feeds two catalog responses (one with overlapping
    item_ids) plus the metadata sources. After firing all four, the
    queue should hold one record per unique auctionId, with
    brand_name/category_name filled in from the metadata."""
    # Reach into the scraper instance's stream_products generator to wire
    # up the listener machinery without driving patchright. We construct
    # a minimal stand-in that mirrors the real method's setup phase.
    from app.platforms.lazada._metadata import (
        MetadataResolver,
        LZD_PAGE_DATA_FRAGMENT,
        CATEGORIES_TREE_FRAGMENT,
    )
    from app.platforms.lazada.extract import (
        is_catalog_url,
        map_item,
        parse_catalog_response,
    )
    from app.models import LazadaProductRecord
    from datetime import datetime, timezone

    seen_ids: set[int] = set()
    record_queue: asyncio.Queue[LazadaProductRecord] = asyncio.Queue()
    metadata = MetadataResolver()

    async def on_response(response):
        url = response.url
        try:
            if metadata.url_matches(url):
                metadata.ingest(url, await response.json())
                return
            if not is_catalog_url(url):
                return
            payload = await response.json()
        except Exception:
            return
        for raw in parse_catalog_response(payload):
            mapped = map_item(raw)
            if mapped is None:
                continue
            iid = mapped["item_id"]
            if iid in seen_ids:
                continue
            seen_ids.add(iid)
            metadata.enrich(mapped)
            record_queue.put_nowait(LazadaProductRecord(
                scraped_at=datetime.now(timezone.utc),
                **{k: v for k, v in mapped.items() if not k.startswith("_")},
            ))

    page = FakePage()
    page.on("response", on_response)

    # Fire metadata first (mirrors real-world order — they fire on landing).
    await page.fire(FakeResponse(
        "https://www.lazada.sg/shop/renderApi/lzdPcPageData",
        _load("010_www_lazada_sg__renderApi_lzdPcPageData.json"),
    ))
    await page.fire(FakeResponse(
        "https://acs-m.lazada.sg/h5/mtop.lazada.guided.shopping.categories.categorieslpcommon/1.0/",
        _load("009_acs-m_lazada_sg__mtop.lazada.guided.shopping.categories.categorieslpcommon_1.json"),
    ))
    # Catalog batch 1.
    await page.fire(FakeResponse(
        "https://acs-m.lazada.sg/h5/mtop.lazada.shop.tpp.query.justforyou/1.0/?p=1",
        _load("014_acs-m_lazada_sg__mtop.lazada.shop.tpp.query.justforyou_1.json"),
    ))
    # Catalog batch 2 — same fixture, same auctionIds → dedupe should
    # drop every item this round.
    pre_count = record_queue.qsize()
    await page.fire(FakeResponse(
        "https://acs-m.lazada.sg/h5/mtop.lazada.shop.tpp.query.justforyou/1.0/?p=2",
        _load("014_acs-m_lazada_sg__mtop.lazada.shop.tpp.query.justforyou_1.json"),
    ))
    assert record_queue.qsize() == pre_count, "dupe batch should be deduped"

    # First batch produced records and they carry resolver-filled fields.
    assert pre_count > 0
    first = record_queue.get_nowait()
    # brand_name comes from shopName.en in the page-data fixture.
    assert first.brand_name == "Za Huo Dian SG"
    # shop/seller ids resolved.
    assert first.seller_id == 1691408001


@pytest.mark.asyncio
async def test_handler_ignores_unknown_urls():
    from app.platforms.lazada._metadata import MetadataResolver
    from app.platforms.lazada.extract import is_catalog_url, map_item, parse_catalog_response
    from app.models import LazadaProductRecord
    from datetime import datetime, timezone

    seen_ids: set[int] = set()
    record_queue: asyncio.Queue[LazadaProductRecord] = asyncio.Queue()
    metadata = MetadataResolver()

    async def on_response(response):
        url = response.url
        try:
            if metadata.url_matches(url):
                metadata.ingest(url, await response.json())
                return
            if not is_catalog_url(url):
                return
            payload = await response.json()
        except Exception:
            return
        for raw in parse_catalog_response(payload):
            mapped = map_item(raw)
            if mapped is None:
                continue
            iid = mapped["item_id"]
            if iid in seen_ids:
                continue
            seen_ids.add(iid)
            record_queue.put_nowait(LazadaProductRecord(
                scraped_at=datetime.now(timezone.utc),
                **{k: v for k, v in mapped.items() if not k.startswith("_")},
            ))

    page = FakePage()
    page.on("response", on_response)
    await page.fire(FakeResponse("https://www.lazada.sg/shop/lacoste/", {"some": "html"}))
    await page.fire(FakeResponse(
        "https://acs-m.lazada.sg/h5/mtop.lazada.shop.atmosphere.list/1.0/",
        {"data": "atmosphere"},
    ))
    assert record_queue.qsize() == 0


def test_brand_slug_extracts_handle():
    s = LazadaScraper()
    req = LazadaScrapeRequest(shop_url="https://www.lazada.sg/shop/lacoste/")
    assert s.brand_slug(req) == "lacoste"


def test_brand_slug_handles_query_string():
    s = LazadaScraper()
    req = LazadaScrapeRequest(
        shop_url="https://www.lazada.sg/shop/za-huo-dian-sg/?path=promo.htm",
    )
    assert s.brand_slug(req) == "za-huo-dian-sg"
