from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from app.platforms.lazada.models import LazadaScrapeRequest
from app.platforms.shopee.models import ShopeeScrapeRequest  # forward; created in Phase 2B


class OfficialSiteScrapeRequest(BaseModel):
    platform: Literal["official_site"] = "official_site"
    brand_url: HttpUrl
    section: str
    categories: list[str]
    max_products: int = 500
    skip_menu_navigation: bool = False


ScrapeRequest = Annotated[
    Union[OfficialSiteScrapeRequest, ShopeeScrapeRequest, LazadaScrapeRequest],
    Field(discriminator="platform"),
]


class ProductRecordBase(BaseModel):
    """Fields populated by every scraper, regardless of platform.

    Platform identity is carried by the enclosing run's `_meta.platform`,
    not on each record — otherwise we'd duplicate that flag across every
    item in a run of potentially hundreds.
    """
    # `extra=ignore` is load-bearing for back-compat: existing run files
    # were written when ProductRecord was a single union model carrying
    # every platform's fields. After this split, loading those files via
    # ShopeeProductRecord.model_validate(...) silently drops the
    # official-site-only `category` (and vice versa) instead of erroring.
    model_config = {"extra": "ignore"}

    product_name: str
    product_url: str | None = None
    image_url: str | None = None
    price: float | None = None
    mrp: float | None = None
    currency: str = ""
    discount_pct: int | None = None
    is_sold_out: bool = False
    scraped_at: datetime


class ShopeeProductRecord(ProductRecordBase):
    item_id: int
    rating_star: float | None = None
    historical_sold_count: int | None = None
    monthly_sold_count: int | None = None
    monthly_sold_text: str | None = None  # human-formatted, e.g. "1.2K"

    # Harvested from /api/v4/shop/rcmd_items
    category_id: str | None = None  # 6-digit "global" catid; stored as str so the UI doesn't render it as a thousands-separated number
    brand: str | None = None
    liked_count: int | None = None
    promotion_labels: list[str] = Field(default_factory=list)
    voucher_code: str | None = None
    voucher_discount: int | None = None  # Shopee 1e5 micro-units (900000 = SGD 9.00 off)


class OfficialSiteProductRecord(ProductRecordBase):
    category: str | None = None


class LazadaProductRecord(ProductRecordBase):
    # Identification
    item_id: int                           # auctionId
    sku_id: int | None = None              # skuId
    sku: str | None = None                 # combined "<auctionId>_<region>-<skuId>"

    # Pricing extras
    saved_text: str | None = None          # "$25.00 saved"

    # Promotion
    # Opaque string — observed values include promPrice / flashSale /
    # mockedSalePrice; treat as free-form, don't gate logic on the enum.
    hit_promotion: str | None = None
    promotion_start_time: int | None = None  # ms epoch (0/None when absent)
    promotion_end_time: int | None = None    # ms epoch
    promotion_labels: list[str] = Field(default_factory=list)  # recommendTexts[].titleText

    # Stock & shipping
    free_shipping: bool = False
    mall: bool = False                     # LazMall flag

    # Popularity / reviews
    rating: float | None = None
    review_count: int | None = None
    # Volume units unverified (Q3 in the spike notes) — stored under volume_*
    # rather than monthly_sold_count to avoid mislabelling before confirmation.
    volume_monthly: int | None = None      # volumePayOrdPrdQty1m
    volume_weekly: int | None = None       # volumePayOrdPrdQty1w
    volume_total: int | None = None        # volumePayOrdPrdQtyStd

    # Shop / brand / category — *_name fields are filled by metadata
    # resolution from the shop landing's lzdPcPageData + categories tree;
    # they are not present in the catalog payload.
    shop_id: int | None = None
    seller_id: int | None = None
    brand_id: int | None = None
    brand_name: str | None = None
    category_id: int | None = None
    category_name: str | None = None       # leaf only
    category_lineage: list[str] = Field(default_factory=list)  # root → leaf names


# Type alias for code that genuinely takes any platform's record.
ProductRecord = ShopeeProductRecord | OfficialSiteProductRecord | LazadaProductRecord


# Single source of truth: platform → record class. Used by the runner
# (loading parent-run records for enrichment) and by get_unified_table
# (building per-platform column descriptors).
RECORD_CLASSES: dict[str, type[ProductRecordBase]] = {
    "shopee": ShopeeProductRecord,
    "official_site": OfficialSiteProductRecord,
    "lazada": LazadaProductRecord,
}


class ShopeeProductUpdate(BaseModel):
    """Late-arriving partial update for a previously-yielded ShopeeProductRecord.

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
