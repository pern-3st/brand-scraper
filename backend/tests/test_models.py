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
