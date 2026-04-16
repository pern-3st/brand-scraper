from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, HttpUrl

from app.platforms.shopee.models import ShopeeScrapeRequest  # forward; created in Phase 2B


class OfficialSiteScrapeRequest(BaseModel):
    platform: Literal["official_site"] = "official_site"
    brand_url: HttpUrl
    section: str
    categories: list[str]
    max_products: int = 10


ScrapeRequest = Annotated[
    Union[OfficialSiteScrapeRequest, ShopeeScrapeRequest],
    Field(discriminator="platform"),
]


class ProductRecord(BaseModel):
    """Unified per-product record emitted by every scraper.

    Core fields are shared. Platform-specific fields default to None/False
    and are populated only by their originating scraper:
      - Shopee: item_id, rating_star, historical_sold_count
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

    # Official-site-only
    category: str | None = None


class ScrapeStartResponse(BaseModel):
    scrape_id: str


class LogEvent(BaseModel):
    message: str
    level: str  # "info" | "success" | "warning" | "error"
