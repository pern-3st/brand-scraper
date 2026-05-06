"""Tests for request-model defaults and validation."""
from __future__ import annotations

import pytest

from app.models import (
    EnrichmentRequest,
    FieldDef,
    FreeformPrompt,
    OfficialSiteScrapeRequest,
    safe_ident,
)


def test_skip_menu_navigation_defaults_to_false():
    req = OfficialSiteScrapeRequest(
        brand_url="https://example.com",
        section="kids",
        categories=["clothing"],
    )
    assert req.skip_menu_navigation is False


def test_skip_menu_navigation_accepts_true():
    req = OfficialSiteScrapeRequest(
        brand_url="https://example.com/kids.html",
        section="kids",
        categories=["clothing"],
        skip_menu_navigation=True,
    )
    assert req.skip_menu_navigation is True


def test_skip_menu_navigation_round_trips_through_dict():
    """Sources persist as plain dict → JSON → dict. Confirm the flag
    survives a round trip so a saved brand spec with skip_menu_navigation=True
    still behaves that way after reload."""
    req = OfficialSiteScrapeRequest(
        brand_url="https://example.com/kids.html",
        section="kids",
        categories=["clothing"],
        skip_menu_navigation=True,
    )
    restored = OfficialSiteScrapeRequest.model_validate(req.model_dump(mode="json"))
    assert restored.skip_menu_navigation is True


# --- enrichment models -------------------------------------------------------


class TestSafeIdent:
    def test_strips_leading_digits(self):
        assert safe_ident("1vegan").startswith("f_")

    def test_replaces_non_word_chars_with_underscore(self):
        assert safe_ident("is vegan?") == "is_vegan_"

    def test_passthrough_clean_identifier(self):
        assert safe_ident("is_vegan") == "is_vegan"

    def test_empty_becomes_placeholder(self):
        assert safe_ident("").startswith("f_")

    def test_only_punctuation_becomes_placeholder(self):
        assert safe_ident("???").startswith("f_")

    def test_leading_underscore_prefixed(self):
        # Reserved-looking identifiers get f_ prefix to avoid dunder conflicts.
        assert not safe_ident("_private").startswith("_")


class TestFieldDef:
    def test_valid_python_ident(self):
        FieldDef(id="description", label="Description", type="str", description="Full text")

    def test_rejects_invalid_ident(self):
        with pytest.raises(ValueError):
            FieldDef(id="is vegan?", label="", type="str", description="")

    def test_rejects_unknown_type(self):
        with pytest.raises(ValueError):
            FieldDef(id="foo", label="", type="bytes", description="")


class TestEnrichmentRequest:
    def test_accepts_curated_only(self):
        req = EnrichmentRequest(curated_fields=["description"], freeform_prompts=[])
        assert req.curated_fields == ["description"]

    def test_accepts_freeform(self):
        req = EnrichmentRequest(
            curated_fields=[],
            freeform_prompts=[
                FreeformPrompt(id="is_vegan", label="Is vegan?", prompt="Does this contain animal products?"),
            ],
        )
        assert req.freeform_prompts[0].id == "is_vegan"

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            EnrichmentRequest(curated_fields=[], freeform_prompts=[])

    def test_rejects_collision_between_curated_and_freeform(self):
        # After sanitisation, user-supplied freeform id collides with curated id.
        with pytest.raises(ValueError):
            EnrichmentRequest(
                curated_fields=["description"],
                freeform_prompts=[
                    FreeformPrompt(id="description", label="Desc", prompt="What?"),
                ],
            )

    def test_rejects_collision_post_sanitise(self):
        # "is vegan?" and "is_vegan_" both sanitise to the same identifier.
        with pytest.raises(ValueError):
            EnrichmentRequest(
                curated_fields=[],
                freeform_prompts=[
                    FreeformPrompt(id="is vegan?", label="", prompt="p1"),
                    FreeformPrompt(id="is_vegan_", label="", prompt="p2"),
                ],
            )

    def test_freeform_id_sanitised_on_construction(self):
        req = EnrichmentRequest(
            curated_fields=[],
            freeform_prompts=[FreeformPrompt(id="is vegan?", label="", prompt="p")],
        )
        # Sanitised in place — downstream code uses .id directly as a Pydantic field name.
        assert req.freeform_prompts[0].id == "is_vegan_"


from datetime import datetime, timezone

from app.models import (
    OfficialSiteProductRecord,
    ShopeeProductRecord,
    ShopeeProductUpdate,
)


class TestShopeeProductRecordMonthlySold:
    def test_defaults_to_none(self):
        rec = ShopeeProductRecord(
            item_id=1,
            product_name="x",
            scraped_at=datetime.now(timezone.utc),
        )
        assert rec.monthly_sold_count is None
        assert rec.monthly_sold_text is None

    def test_round_trips_through_json(self):
        rec = ShopeeProductRecord(
            item_id=1,
            product_name="x",
            scraped_at=datetime.now(timezone.utc),
            monthly_sold_count=42,
            monthly_sold_text="42 sold/mo",
        )
        restored = ShopeeProductRecord.model_validate(rec.model_dump(mode="json"))
        assert restored.monthly_sold_count == 42
        assert restored.monthly_sold_text == "42 sold/mo"


class TestShopeeProductUpdate:
    def test_minimal(self):
        upd = ShopeeProductUpdate(item_id=123)
        assert upd.item_id == 123
        assert upd.monthly_sold_count is None
        assert upd.monthly_sold_text is None

    def test_round_trips(self):
        upd = ShopeeProductUpdate(item_id=123, monthly_sold_count=42, monthly_sold_text="42 sold")
        restored = ShopeeProductUpdate.model_validate(upd.model_dump(mode="json"))
        assert restored == upd

    def test_rejects_missing_item_id(self):
        with pytest.raises(ValueError):
            ShopeeProductUpdate(monthly_sold_count=42)


class TestShopeeProductRecordRcmdItemsFields:
    def test_new_fields_default_to_none_or_empty(self):
        rec = ShopeeProductRecord(
            item_id=1,
            product_name="x",
            scraped_at=datetime.now(timezone.utc),
        )
        assert rec.category_id is None
        assert rec.brand is None
        assert rec.liked_count is None
        assert rec.promotion_labels == []
        assert rec.voucher_code is None
        assert rec.voucher_discount is None


class TestShopeeProductUpdateRcmdItemsFields:
    def test_new_fields_default_to_none(self):
        upd = ShopeeProductUpdate(item_id=1)
        assert upd.category_id is None
        assert upd.brand is None
        assert upd.liked_count is None
        assert upd.promotion_labels is None
        assert upd.voucher_code is None
        assert upd.voucher_discount is None


class TestOfficialSiteProductRecord:
    def test_round_trips(self):
        rec = OfficialSiteProductRecord(
            product_name="x",
            scraped_at=datetime.now(timezone.utc),
            category="shoes",
        )
        restored = OfficialSiteProductRecord.model_validate(
            rec.model_dump(mode="json")
        )
        assert restored.category == "shoes"
        assert restored.product_name == "x"


class TestProductRecordExtraIgnore:
    """Loading legacy unified-schema run files: each record is a superset of
    its platform's fields. `extra=ignore` on ProductRecordBase must silently
    drop the foreign-platform fields rather than raising — otherwise old
    run files can't be loaded after the split."""

    def test_shopee_record_drops_official_site_fields(self):
        # Legacy shape: a Shopee record with the official-site `category` field.
        rec = ShopeeProductRecord.model_validate({
            "item_id": 1,
            "product_name": "x",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "category": "ignored-on-shopee",
        })
        assert "category" not in rec.model_dump()

    def test_official_site_record_drops_shopee_fields(self):
        rec = OfficialSiteProductRecord.model_validate({
            "product_name": "x",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "item_id": 999,
            "rating_star": 4.5,
            "monthly_sold_count": 100,
            "category_id": "abc",
            "promotion_labels": ["A", "B"],
        })
        dumped = rec.model_dump()
        for shopee_only in (
            "item_id",
            "rating_star",
            "monthly_sold_count",
            "category_id",
            "promotion_labels",
        ):
            assert shopee_only not in dumped
