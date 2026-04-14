from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, HttpUrl

from app.platforms.shopee.models import ShopeeScrapeRequest  # forward; created in Phase 2B


class OfficialSiteScrapeRequest(BaseModel):
    platform: Literal["official_site"] = "official_site"
    brand_url: HttpUrl
    section: str
    categories: list[str]
    max_products: int = 10


class CategoryResult(BaseModel):
    category: str
    status: str  # "found" | "not_found"
    lowest_price: float | None = None
    highest_price: float | None = None
    products_scanned: int = 0


ScrapeRequest = Annotated[
    Union[OfficialSiteScrapeRequest, ShopeeScrapeRequest],
    Field(discriminator="platform"),
]


class ScrapeStartResponse(BaseModel):
    scrape_id: str


class LogEvent(BaseModel):
    message: str
    level: str  # "info" | "success" | "warning" | "error"
