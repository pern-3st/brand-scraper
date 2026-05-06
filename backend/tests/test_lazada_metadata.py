"""Tests for MetadataResolver — lzdPcPageData + categories tree handling."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.platforms.lazada._metadata import MetadataResolver

CAPTURE_DIR = (
    Path(__file__).resolve().parent.parent / "scripts" / "lazada_spike_captures"
)

PAGE_DATA_FIXTURE = "010_www_lazada_sg__renderApi_lzdPcPageData.json"
CATEGORIES_FIXTURE = "009_acs-m_lazada_sg__mtop.lazada.guided.shopping.categories.categorieslpcommon_1.json"


def _load(name: str) -> dict:
    return json.loads((CAPTURE_DIR / name).read_text())


class TestPageDataIngestion:
    def test_extracts_shop_and_seller_ids(self):
        r = MetadataResolver()
        r.ingest(
            "https://www.lazada.sg/shop/renderApi/lzdPcPageData?x=1",
            _load(PAGE_DATA_FIXTURE),
        )
        # Captured globalData for za-huo-dian-sg.
        assert r.shop_id is not None
        assert r.seller_id == 1691408001

    def test_walks_components_for_shop_name(self):
        """Component id rotates per page so positional indexing isn't safe;
        the resolver must walk the dict for the entry containing
        formData.shopName."""
        r = MetadataResolver()
        r.ingest(
            "https://www.lazada.sg/shop/renderApi/lzdPcPageData",
            _load(PAGE_DATA_FIXTURE),
        )
        assert r.shop_name == "Za Huo Dian SG"
        # For single-brand shops, brand_name == shopName.en.
        assert r.brand_name == "Za Huo Dian SG"

    def test_graceful_when_globaldata_missing_optional_fields(self):
        """Non-campaign shops omit campaignId/promotionTag — the resolver
        treats them as optional and still extracts shop/seller ids."""
        synthetic = {
            "result": {
                "globalData": {"shopId": 999, "sellerId": 888},
                "components": {},
            },
        }
        r = MetadataResolver()
        r.ingest("https://www.lazada.sg/shop/renderApi/lzdPcPageData", synthetic)
        assert r.shop_id == 999
        assert r.seller_id == 888
        assert r.shop_name is None
        assert r.brand_name is None


class TestCategoriesIngestion:
    def test_flattens_l1_l2_l3(self):
        r = MetadataResolver()
        r.ingest(
            "https://acs-m.lazada.sg/h5/mtop.lazada.guided.shopping.categories.categorieslpcommon/1.0/",
            _load(CATEGORIES_FIXTURE),
        )
        assert r.category_names, "expected non-empty category id→name map"
        # L1: "Electronic Accessories" id=8827326
        assert r.category_names.get(8827326) == "Electronic Accessories"
        # L2: "Mobile Accessories" id=9536
        assert r.category_names.get(9536) == "Mobile Accessories"
        # L3: "Power Banks" id=9562
        assert r.category_names.get(9562) == "Power Banks"


class TestEnrich:
    def test_fills_brand_and_shop_ids(self):
        r = MetadataResolver()
        r.brand_name = "Lacoste"
        r.shop_id = 1873697
        r.seller_id = 1393488045
        item: dict = {"item_id": 1, "category_id": 9562}
        r.enrich(item)
        assert item["brand_name"] == "Lacoste"
        assert item["shop_id"] == 1873697
        assert item["seller_id"] == 1393488045

    def test_translates_lineage_when_categories_known(self):
        r = MetadataResolver()
        r.category_names = {1: "Root", 2: "Mid", 3: "Leaf"}
        item: dict = {
            "item_id": 1,
            "category_id": 3,
            "_category_id_lineage": [1, 2, 3],
        }
        r.enrich(item)
        assert item["category_name"] == "Leaf"
        assert item["category_lineage"] == ["Root", "Mid", "Leaf"]
        # The internal lineage key must be popped so it doesn't bleed
        # into LazadaProductRecord(**item).
        assert "_category_id_lineage" not in item

    def test_does_not_invent_lineage_when_categories_missing(self):
        r = MetadataResolver()
        item: dict = {
            "item_id": 1,
            "category_id": 3,
            "_category_id_lineage": [1, 2, 3],
        }
        r.enrich(item)
        assert "category_name" not in item
        assert "category_lineage" not in item

    def test_does_not_clobber_existing_values(self):
        r = MetadataResolver()
        r.brand_name = "From Resolver"
        item: dict = {
            "item_id": 1,
            "brand_name": "From Item",
            "category_id": None,
        }
        r.enrich(item)
        assert item["brand_name"] == "From Item"


class TestWaitUntilReady:
    @pytest.mark.asyncio
    async def test_returns_true_when_both_arrive(self):
        r = MetadataResolver()
        r.ingest(
            "https://www.lazada.sg/shop/renderApi/lzdPcPageData",
            _load(PAGE_DATA_FIXTURE),
        )
        r.ingest(
            "https://acs-m.lazada.sg/h5/mtop.lazada.guided.shopping.categories.categorieslpcommon/1.0/",
            _load(CATEGORIES_FIXTURE),
        )
        ok = await r.wait_until_ready(timeout=0.1)
        assert ok is True

    @pytest.mark.asyncio
    async def test_times_out_when_one_missing(self):
        r = MetadataResolver()
        r.ingest(
            "https://www.lazada.sg/shop/renderApi/lzdPcPageData",
            _load(PAGE_DATA_FIXTURE),
        )
        # categories never arrives.
        ok = await r.wait_until_ready(timeout=0.1)
        assert ok is False
