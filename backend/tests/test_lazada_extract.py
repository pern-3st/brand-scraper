"""Tests for lazada.extract — envelope-aware catalog parsing + per-item mapping.

The shop SPA picks one of three catalog endpoints depending on whether
the shop has an active campaign. Per-item shape is identical across
all three; only the envelope differs. These tests assert that
parse_catalog_response handles each shape and that map_item produces
the same per-item dict regardless of source envelope.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.platforms.lazada.extract import (
    is_catalog_url,
    map_item,
    parse_catalog_response,
    shop_handle_from_url,
)

# Captures collected during the spike. Only the non-campaign run made
# it onto disk (the spike script wipes the dir on each run); we
# synthesise a minimal campaign envelope inline.
CAPTURE_DIR = (
    Path(__file__).resolve().parent.parent / "scripts" / "lazada_spike_captures"
)


def _load(name: str) -> dict:
    return json.loads((CAPTURE_DIR / name).read_text())


JUSTFORYOU_FIXTURE = "014_acs-m_lazada_sg__mtop.lazada.shop.tpp.query.justforyou_1.json"
SMART_PRODUCTS_FIXTURE = "021_acs-m_lazada_sg__mtop.lazada.shop.smart.products.query_1.json"


# Synthetic campaign-endpoint envelope — same per-item schema as the
# captured ones, wrapped in result.data[]. The real spike's campaign
# captures (Lacoste) weren't preserved; this stand-in keeps the
# round-trip test honest without taking another live capture.
CAMPAIGN_ENVELOPE = {
    "code": 0,
    "success": True,
    "result": {
        "data": [
            {
                "auctionId": 3604705412,
                "skuId": 23782247898,
                "sku": "3604705412_SGAMZ-23782247898",
                "title": "Lacoste Polo Classic Fit",
                "pdpUrl": "https://www.lazada.sg/products/pdp-i3604705412-s23782247898.html",
                "imageUrl": "//sg-test-11.slatic.net/p/lacoste.jpg",
                "price": 69.0,
                "discountPrice": 44.0,
                "discount": 36.23,
                "savedText": "$25.00 saved",
                "hitPromotion": "promPrice",
                "promotionStartTime": 0,
                "promotionEndTime": 2147483647000,
                "recommendTexts": [
                    {"titleText": "Sale｜$25.00 off", "textColor": "#FF0066"},
                ],
                "inStock": 1,
                "freeShipping": False,
                "mall": True,
                "rating": 5.0,
                "reviews": 7,
                "volumePayOrdPrdQty1m": 12,
                "volumePayOrdPrdQty1w": 3,
                "volumePayOrdPrdQtyStd": 84,
                "shopId": 1873697,
                "sellerId": 1393488045,
                "brandId": 12345,
                "categoryId": 10001234,
                "categories": [10000001, 10000010, 10001234],
            },
        ],
        "totalCount": 1,
        "totalPage": 1,
    },
}


class TestParseCatalogResponse:
    def test_campaign_envelope(self):
        items = parse_catalog_response(CAMPAIGN_ENVELOPE)
        assert len(items) == 1
        assert items[0]["auctionId"] == 3604705412

    def test_justforyou_envelope(self):
        payload = _load(JUSTFORYOU_FIXTURE)
        items = parse_catalog_response(payload)
        assert len(items) > 0
        assert all(isinstance(it, dict) for it in items)
        assert all("auctionId" in it for it in items)

    def test_smart_products_envelope(self):
        payload = _load(SMART_PRODUCTS_FIXTURE)
        items = parse_catalog_response(payload)
        assert len(items) > 0
        assert all(isinstance(it, dict) for it in items)
        assert all("auctionId" in it for it in items)

    def test_unknown_envelope_returns_empty(self):
        assert parse_catalog_response({"foo": "bar"}) == []
        assert parse_catalog_response([]) == []
        assert parse_catalog_response(None) == []  # type: ignore[arg-type]


class TestMapItem:
    def test_full_campaign_item(self):
        item = CAMPAIGN_ENVELOPE["result"]["data"][0]
        out = map_item(item)
        assert out is not None
        # Base fields
        assert out["product_name"] == "Lacoste Polo Classic Fit"
        assert out["product_url"].startswith("https://www.lazada.sg/products/")
        assert out["image_url"].startswith("https://"), "should prefix protocol-relative URL"
        assert out["price"] == 44.0
        assert out["mrp"] == 69.0
        assert out["currency"] == "SGD"
        assert out["discount_pct"] == 36
        assert out["is_sold_out"] is False
        # Lazada-specific
        assert out["item_id"] == 3604705412
        assert out["sku_id"] == 23782247898
        assert out["sku"] == "3604705412_SGAMZ-23782247898"
        assert out["saved_text"] == "$25.00 saved"
        assert out["hit_promotion"] == "promPrice"
        assert out["promotion_end_time"] == 2147483647000
        assert out["promotion_labels"] == ["Sale｜$25.00 off"]
        assert out["mall"] is True
        assert out["rating"] == 5.0
        assert out["review_count"] == 7
        assert out["volume_monthly"] == 12
        assert out["volume_weekly"] == 3
        assert out["volume_total"] == 84
        assert out["shop_id"] == 1873697
        assert out["seller_id"] == 1393488045
        assert out["brand_id"] == 12345
        assert out["category_id"] == 10001234
        assert out["_category_id_lineage"] == [10000001, 10000010, 10001234]

    def test_justforyou_item_maps_same_shape_as_campaign(self):
        """All three envelopes share the per-item schema — confirm the
        captured non-campaign payload produces a dict with the same keys
        as the campaign one."""
        items = parse_catalog_response(_load(JUSTFORYOU_FIXTURE))
        assert items, "fixture should contain at least one item"
        out = map_item(items[0])
        assert out is not None
        campaign_out = map_item(CAMPAIGN_ENVELOPE["result"]["data"][0])
        assert campaign_out is not None
        assert set(out.keys()) == set(campaign_out.keys())

    def test_smart_products_item_maps_same_shape(self):
        items = parse_catalog_response(_load(SMART_PRODUCTS_FIXTURE))
        assert items
        out = map_item(items[0])
        assert out is not None
        # Sanity-check a couple of base fields.
        assert isinstance(out["item_id"], int)
        assert out["currency"] == "SGD"

    def test_missing_required_fields_returns_none(self):
        assert map_item({}) is None
        assert map_item({"auctionId": 1}) is None  # no title/pdpUrl
        assert map_item({"auctionId": 1, "title": "x"}) is None  # no pdpUrl

    def test_missing_discount_keeps_discount_pct_none(self):
        item = {
            "auctionId": 1,
            "title": "x",
            "pdpUrl": "https://www.lazada.sg/products/pdp-i1.html",
            "price": 10.0,
        }
        out = map_item(item)
        assert out is not None
        assert out["discount_pct"] is None
        assert out["price"] == 10.0
        assert out["mrp"] == 10.0

    def test_in_stock_zero_marks_sold_out(self):
        item = {
            "auctionId": 1,
            "title": "x",
            "pdpUrl": "https://www.lazada.sg/products/pdp-i1.html",
            "price": 5.0,
            "inStock": 0,
        }
        out = map_item(item)
        assert out is not None
        assert out["is_sold_out"] is True


class TestIsCatalogUrl:
    def test_recognises_all_three_endpoints(self):
        assert is_catalog_url(
            "https://www.lazada.sg/shop/site/api/shop/campaignTppProducts/query?shopId=1"
        )
        assert is_catalog_url(
            "https://acs-m.lazada.sg/h5/mtop.lazada.shop.tpp.query.justforyou/1.0/?x=1"
        )
        assert is_catalog_url(
            "https://acs-m.lazada.sg/h5/mtop.lazada.shop.smart.products.query/1.0/?x=1"
        )

    def test_rejects_other_endpoints(self):
        assert not is_catalog_url("https://www.lazada.sg/shop/lacoste/")
        assert not is_catalog_url(
            "https://acs-m.lazada.sg/h5/mtop.lazada.shop.atmosphere.list/1.0/"
        )


class TestShopHandleFromUrl:
    def test_basic_lazada_sg(self):
        assert shop_handle_from_url("https://www.lazada.sg/shop/lacoste/") == "lacoste"

    def test_handles_query_and_fragment(self):
        url = "https://www.lazada.sg/shop/za-huo-dian-sg/?path=promotion-1.htm&tab=promotion#anchor"
        assert shop_handle_from_url(url) == "za-huo-dian-sg"

    def test_naked_lazada_host(self):
        assert shop_handle_from_url("https://lazada.sg/shop/foo/") == "foo"

    def test_rejects_other_regions(self):
        with pytest.raises(ValueError):
            shop_handle_from_url("https://www.lazada.com.my/shop/foo/")

    def test_rejects_non_shop_path(self):
        with pytest.raises(ValueError):
            shop_handle_from_url("https://www.lazada.sg/products/pdp-i123.html")
