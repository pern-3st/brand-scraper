"""Pure helpers for Shopee's `/api/v4/shop/rcmd_items` XHR.

This endpoint fires automatically on every shop-grid navigation and
delivers per-card monthly_sold, catid, brand, liked_count, promotion
labels, and active voucher code/discount — all in one envelope, with no
PDP visits required. Replaces the older recommend-XHR side-channel which
required PDP seed visits and only achieved ~30% monthly coverage.

Display-name resolution (catid → "Men > Shoes") is intentionally NOT
implemented; the catid space rcmd_items uses is disjoint from shopee.sg's
public resolver. See plan Task 4 (SKIPPED) and Task 0 probe results.

See docs/plans/2026-05-05-shopee-rcmd-items-migration.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HarvestEntry:
    monthly_text: str | None
    monthly_int: int | None
    catid: int | None
    brand: str | None
    liked_count: int | None
    promotion_labels: list[str] = field(default_factory=list)
    voucher_code: str | None = None
    voucher_discount: int | None = None  # Shopee 1e5 micro-units


# Matches "15 Sold/Month", "1.2K Sold/Month", "3K Sold/Month".
# We anchor on "Sold/Month" rather than ".*" suffixes so we don't quietly
# accept random strings.
_MONTHLY_RE = re.compile(
    r"\s*([\d.]+)\s*([KkMm])?\s*Sold\s*/\s*Month\s*$"
)


def parse_monthly_text(text: str | None) -> int | None:
    """Parse Shopee's display string into an integer count.

    Shopee's raw `monthly_sold_count` integer is always 0 regardless of
    the actual value (spike-verified across 29 cards on 2026-05-05) — the
    text field is the only authoritative source. Returns None for
    null/garbage input; callers can distinguish "no data" (None) from
    "explicitly zero monthly sales" by checking the source text directly.
    """
    if not text:
        return None
    m = _MONTHLY_RE.match(text)
    if not m:
        return None
    n = float(m.group(1))
    suffix = (m.group(2) or "").lower()
    if suffix == "k":
        n *= 1000
    elif suffix == "m":
        n *= 1_000_000
    return int(n)


def _flatten_promotion_labels(asset: dict[str, Any]) -> list[str]:
    """Pull display strings out of item_card_displayed_asset.promotion_label_list."""
    out: list[str] = []
    for label in (asset.get("promotion_label_list") or []):
        if not isinstance(label, dict):
            continue
        text = ((label.get("data") or {}).get("text") or "").strip()
        if text:
            out.append(text)
    return out


def parse_rcmd_items(payload: dict[str, Any]) -> dict[int, HarvestEntry]:
    """Walk a rcmd_items response into ``{itemid: HarvestEntry}``.

    Returns an empty dict for unexpected shapes (Shopee occasionally
    returns error envelopes; treat as no-ops, not exceptions).

    Per spike: items missing `monthly_sold_count_text` always have
    `historical_sold_count_text: null`, i.e. brand-new listings with no
    sales. We surface this as `monthly_text=None, monthly_int=0` rather
    than dropping the value — callers can distinguish "no display string"
    from "no data" via the text field.

    Voucher details live under `item_card_display_price.recommended_platform_voucher_info`
    (NOT at the card root — that path is reserved for a different envelope
    that's null in shop-context responses).
    """
    out: dict[int, HarvestEntry] = {}
    cards = (
        ((payload.get("data") or {}).get("centralize_item_card") or {}).get("item_cards")
        or []
    )
    for card in cards:
        if not isinstance(card, dict):
            continue
        iid = card.get("itemid")
        if not iid:
            continue
        sc = card.get("item_card_display_sold_count") or {}
        monthly_text = sc.get("monthly_sold_count_text")
        # The raw `monthly_sold_count` int is unreliable (always 0 in the
        # spike fixture) — derive the count from the text.
        parsed_int = parse_monthly_text(monthly_text)
        monthly_int = parsed_int if parsed_int is not None else 0
        brand = (card.get("global_brand") or {}).get("display_name")
        asset = card.get("item_card_displayed_asset") or {}
        promotion_labels = _flatten_promotion_labels(asset)
        # Voucher envelope nests under display_price.
        voucher = (
            (card.get("item_card_display_price") or {})
            .get("recommended_platform_voucher_info") or {}
        )
        voucher_code = voucher.get("voucher_code") or None
        voucher_discount = voucher.get("voucher_discount")
        if voucher_discount is not None and not isinstance(voucher_discount, int):
            voucher_discount = None  # defensive — the field is documented as int
        out[int(iid)] = HarvestEntry(
            monthly_text=monthly_text,
            monthly_int=monthly_int,
            catid=card.get("catid"),
            brand=brand,
            liked_count=card.get("liked_count"),
            promotion_labels=promotion_labels,
            voucher_code=voucher_code,
            voucher_discount=voucher_discount,
        )
    return out


def merge_into_harvest(
    harvest: dict[int, HarvestEntry],
    parsed: dict[int, HarvestEntry],
) -> int:
    """Merge parsed entries into the running harvest dict.

    Returns the number of items whose `monthly_text` is now populated for
    the first time (i.e. either freshly added with non-null monthly, or
    existing-null upgraded to non-null). Already-populated entries are
    never overwritten — Shopee occasionally returns rounded / less-precise
    values for items that were previously seen with a more specific value,
    and we trust the first non-null sighting.

    For non-monthly fields (catid, brand, liked_count, promotion_labels,
    voucher_code, voucher_discount), null values are upgraded in-place
    but non-null values are NOT overwritten (same first-sighting-wins rule).
    """
    newly_covered = 0
    for iid, fields in parsed.items():
        existing = harvest.get(iid)
        if existing is None:
            harvest[iid] = fields
            if fields.monthly_text is not None:
                newly_covered += 1
            continue
        if existing.monthly_text is None and fields.monthly_text is not None:
            existing.monthly_text = fields.monthly_text
            existing.monthly_int = fields.monthly_int
            newly_covered += 1
        if existing.catid is None and fields.catid is not None:
            existing.catid = fields.catid
        if existing.brand is None and fields.brand is not None:
            existing.brand = fields.brand
        if existing.liked_count is None and fields.liked_count is not None:
            existing.liked_count = fields.liked_count
        if not existing.promotion_labels and fields.promotion_labels:
            existing.promotion_labels = fields.promotion_labels
        if existing.voucher_code is None and fields.voucher_code is not None:
            existing.voucher_code = fields.voucher_code
        if existing.voucher_discount is None and fields.voucher_discount is not None:
            existing.voucher_discount = fields.voucher_discount
    return newly_covered
