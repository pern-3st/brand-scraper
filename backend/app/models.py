from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from app.platforms.shopee.models import ShopeeScrapeRequest  # forward; created in Phase 2B


class OfficialSiteScrapeRequest(BaseModel):
    platform: Literal["official_site"] = "official_site"
    brand_url: HttpUrl
    section: str
    categories: list[str]
    max_products: int = 500
    skip_menu_navigation: bool = False


ScrapeRequest = Annotated[
    Union[OfficialSiteScrapeRequest, ShopeeScrapeRequest],
    Field(discriminator="platform"),
]


class ProductRecord(BaseModel):
    """Unified per-product record emitted by every scraper.

    Core fields are shared. Platform-specific fields default to None/False
    and are populated only by their originating scraper:
      - Shopee: item_id, rating_star, historical_sold_count, monthly_sold_count,
        category_id, brand, liked_count, promotion_labels, voucher_code,
        voucher_discount
      - Official-site: category

    Platform identity is carried by the enclosing run's `_meta.platform`,
    not on each record — otherwise we'd duplicate that flag across every
    item in a run of potentially hundreds.
    """
    # Core (populated by every scraper)
    product_name: str
    product_url: str | None = None
    image_url: str | None = None
    price: float | None = None
    mrp: float | None = None
    currency: str = ""
    discount_pct: int | None = None
    is_sold_out: bool = False
    scraped_at: datetime

    # Shopee-only
    item_id: int | None = None
    rating_star: float | None = None
    historical_sold_count: int | None = None
    monthly_sold_count: int | None = None
    monthly_sold_text: str | None = None  # human-formatted, e.g. "1.2K"

    # Shopee-only — harvested from /api/v4/shop/rcmd_items
    category_id: str | None = None  # 6-digit "global" catid; stored as str so the UI doesn't render it as a thousands-separated number
    brand: str | None = None
    liked_count: int | None = None
    promotion_labels: list[str] = Field(default_factory=list)
    voucher_code: str | None = None
    voucher_discount: int | None = None  # Shopee 1e5 micro-units (900000 = SGD 9.00 off)

    # Official-site-only
    category: str | None = None


class ProductUpdate(BaseModel):
    """Late-arriving partial update for a previously-yielded ProductRecord.

    Shopee's rcmd_items XHR delivers monthly_sold + category_id + brand + likes
    + promo metadata + voucher details asynchronously from grid extraction.
    The runner matches by `item_id` and mutates the existing record; unknown
    ids are dropped with a log line. `category` (the display name) is not
    included — see docs/plans/2026-05-05-shopee-rcmd-items-migration.md
    Task 4 (SKIPPED).
    """
    item_id: int
    monthly_sold_count: int | None = None
    monthly_sold_text: str | None = None
    category_id: str | None = None
    brand: str | None = None
    liked_count: int | None = None
    promotion_labels: list[str] | None = None
    voucher_code: str | None = None
    voucher_discount: int | None = None


class ScrapeStartResponse(BaseModel):
    scrape_id: str


class LogEvent(BaseModel):
    message: str
    level: str  # "info" | "success" | "warning" | "error"


# --- enrichment --------------------------------------------------------------

FieldType = Literal["str", "int", "float", "bool", "list[str]"]

_IDENT_RE = re.compile(r"\W|^(?=\d)")


def safe_ident(raw: str) -> str:
    """Coerce arbitrary user input into a valid Python identifier usable as a
    Pydantic field name. Matches the spec in
    ``docs/plans/2026-04-24-product-detail-enrichment-design.md``.
    """
    cleaned = _IDENT_RE.sub("_", raw.strip())
    if not cleaned or cleaned.startswith("_"):
        cleaned = f"f_{cleaned.lstrip('_')}"
    return cleaned


class FieldDef(BaseModel):
    """Curated enrichment field exposed by a platform's catalog."""
    id: str
    label: str
    type: FieldType
    description: str
    category: str | None = None

    @field_validator("id")
    @classmethod
    def _ident_must_be_valid(cls, v: str) -> str:
        if not v.isidentifier():
            raise ValueError(f"FieldDef.id {v!r} is not a valid Python identifier")
        return v


class FreeformPrompt(BaseModel):
    """User-authored question for a platform that supports freeform prompts."""
    id: str
    label: str
    prompt: str

    @field_validator("id", mode="before")
    @classmethod
    def _sanitise_id(cls, v: Any) -> Any:
        if isinstance(v, str):
            return safe_ident(v)
        return v


class EnrichmentRequest(BaseModel):
    curated_fields: list[str]
    freeform_prompts: list[FreeformPrompt]

    @model_validator(mode="after")
    def _check_non_empty_and_unique(self) -> "EnrichmentRequest":
        if not self.curated_fields and not self.freeform_prompts:
            raise ValueError("enrichment request must specify at least one field or prompt")
        seen: set[str] = set()
        for fid in self.curated_fields:
            if fid in seen:
                raise ValueError(f"duplicate field id {fid!r}")
            seen.add(fid)
        for prompt in self.freeform_prompts:
            if prompt.id in seen:
                raise ValueError(
                    f"enrichment field id {prompt.id!r} collides with another field or prompt"
                )
            seen.add(prompt.id)
        return self


class EnrichmentRow(BaseModel):
    """One extractor result for one product, written to the enrichment file."""
    product_key: str
    values: dict[str, Any]
    errors: dict[str, str] = Field(default_factory=dict)
    enriched_at: datetime


class UnifiedColumn(BaseModel):
    """Column descriptor returned by ``GET /runs/{id}/table``."""
    id: str
    label: str
    type: FieldType | None = None  # None when the scrape schema field has no mappable type (e.g. datetime)
    source: Literal["scrape", "enrichment"]
    enrichment_id: str | None = None


class UnifiedTable(BaseModel):
    columns: list[UnifiedColumn]
    rows: list[dict[str, Any]]
