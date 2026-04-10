from pydantic import BaseModel, HttpUrl


class ScrapeRequest(BaseModel):
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


class ScrapeResponse(BaseModel):
    brand: str
    section: str
    currency: str
    results: list[CategoryResult]


class ScrapeStartResponse(BaseModel):
    scrape_id: str


class LogEvent(BaseModel):
    message: str
    level: str  # "info" | "success" | "warning" | "error"
