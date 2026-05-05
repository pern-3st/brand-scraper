"""Tests for the pure rcmd_items parser used by the Shopee harvest."""
import json
from pathlib import Path

import pytest

from app.platforms.shopee._rcmd_items_harvest import (
    HarvestEntry,
    merge_into_harvest,
    parse_monthly_text,
    parse_rcmd_items,
)

FIXTURE = Path(__file__).parent / "fixtures" / "shopee" / "rcmd_items_levis_p1.json"


@pytest.fixture
def levis_p1_payload() -> dict:
    return json.loads(FIXTURE.read_text())


# --- parse_monthly_text --------------------------------------------------

class TestParseMonthlyText:
    @pytest.mark.parametrize("text,expected", [
        ("15 Sold/Month", 15),
        ("8 Sold/Month", 8),
        ("1.2K Sold/Month", 1200),
        ("3K Sold/Month", 3000),
        (None, None),
        ("", None),
        ("garbage", None),
    ])
    def test_parses_known_shapes(self, text, expected):
        assert parse_monthly_text(text) == expected


# --- parse_rcmd_items ----------------------------------------------------

class TestParseRcmdItems:
    def test_empty_payload(self):
        assert parse_rcmd_items({}) == {}

    def test_missing_centralize(self):
        assert parse_rcmd_items({"data": {}}) == {}

    def test_extracts_all_cards_from_fixture(self, levis_p1_payload):
        out = parse_rcmd_items(levis_p1_payload)
        assert len(out) == 29  # rcmd_items_20260505_140922.json

    def test_monthly_int_is_parsed_from_text_not_raw_int_field(self, levis_p1_payload):
        """The raw `monthly_sold_count` integer is always 0 in the response —
        the truth lives in `monthly_sold_count_text`. The parser must derive
        the int from the text; trusting the raw int yields all-zero data.
        """
        out = parse_rcmd_items(levis_p1_payload)
        with_text = [e for e in out.values() if e.monthly_text is not None]
        # Spike: 25/29 have explicit monthly text.
        assert len(with_text) == 25
        # Every with-text entry must have a positive monthly_int parsed from it.
        assert all((e.monthly_int or 0) > 0 for e in with_text)
        # And entries without text fall back to 0 (brand-new-listing fixtures).
        without_text = [e for e in out.values() if e.monthly_text is None]
        assert all(e.monthly_int == 0 for e in without_text)

    def test_catid_for_every_card(self, levis_p1_payload):
        out = parse_rcmd_items(levis_p1_payload)
        assert all(e.catid is not None for e in out.values())

    def test_brand_populated_for_levis(self, levis_p1_payload):
        out = parse_rcmd_items(levis_p1_payload)
        brands = {e.brand for e in out.values() if e.brand}
        assert "Levi's" in brands

    def test_promotion_labels_extracted(self, levis_p1_payload):
        out = parse_rcmd_items(levis_p1_payload)
        # Spike: 25/29 cards have at least one promo label, with display
        # strings like "Any 2 enjoy 5% off" / "New Arrival".
        with_labels = [e for e in out.values() if e.promotion_labels]
        assert len(with_labels) >= 20
        # Display text must round-trip through the parser.
        all_texts = {t for e in out.values() for t in e.promotion_labels}
        assert any("enjoy" in t.lower() or "arrival" in t.lower() for t in all_texts)

    def test_voucher_code_and_discount_when_present(self, levis_p1_payload):
        """Voucher path lives under item_card_display_price.recommended_platform_voucher_info,
        NOT at the card root. Spike: 21/29 cards populated."""
        out = parse_rcmd_items(levis_p1_payload)
        coded = [e for e in out.values() if e.voucher_code]
        assert len(coded) >= 18
        # Both fields populate together (voucher_info envelope is all-or-nothing).
        assert all(e.voucher_discount is not None and e.voucher_discount > 0 for e in coded)
        # Discount is in 1e5 micro-units — values should look like 900000, 2500000.
        assert all(e.voucher_discount >= 100_000 for e in coded)

    def test_skips_units_without_itemid(self):
        payload = {"data": {"centralize_item_card": {"item_cards": [
            {"itemid": None, "catid": 1},
        ]}}}
        assert parse_rcmd_items(payload) == {}


# --- merge_into_harvest --------------------------------------------------

def _entry(**kwargs) -> HarvestEntry:
    base = dict(monthly_text=None, monthly_int=0, catid=None, brand=None,
                liked_count=None, promotion_labels=[], voucher_code=None,
                voucher_discount=None)
    base.update(kwargs)
    return HarvestEntry(**base)


class TestMergeIntoHarvest:
    def test_adds_new_item(self):
        h: dict[int, HarvestEntry] = {}
        n = merge_into_harvest(h, {1: _entry(monthly_text="42 Sold/Month", monthly_int=42)})
        assert n == 1
        assert h[1].monthly_text == "42 Sold/Month"

    def test_does_not_overwrite_explicit_monthly(self):
        """First non-null sighting wins (matches existing recommend-harvest semantics)."""
        h = {1: _entry(monthly_text="10 Sold/Month", monthly_int=10)}
        n = merge_into_harvest(h, {1: _entry(monthly_text="9999", monthly_int=9999)})
        assert n == 0
        assert h[1].monthly_text == "10 Sold/Month"

    def test_upgrades_null_text_with_real_text(self):
        h = {1: _entry(monthly_text=None, monthly_int=0, catid=100)}
        n = merge_into_harvest(h, {1: _entry(monthly_text="50 Sold/Month", monthly_int=50, catid=100)})
        assert n == 1
        assert h[1].monthly_text == "50 Sold/Month"
        assert h[1].monthly_int == 50

    def test_fills_in_null_catid_brand_voucher(self):
        h = {1: _entry()}
        merge_into_harvest(h, {1: _entry(
            catid=100011, brand="Levi's",
            voucher_code="9OFF70", voucher_discount=900000,
        )})
        h_after = h[1]
        assert h_after.catid == 100011
        assert h_after.brand == "Levi's"
        assert h_after.voucher_code == "9OFF70"
        assert h_after.voucher_discount == 900000
