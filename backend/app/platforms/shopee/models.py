from datetime import datetime
from typing import Literal

from pydantic import BaseModel, HttpUrl


class ShopeeScrapeRequest(BaseModel):
    platform: Literal["shopee"] = "shopee"
    shop_url: HttpUrl
    max_products: int = 200


class ShopeeProductRecord(BaseModel):
    """Per-product data extracted from the Shopee shop-grid DOM.

    Fields in the original design doc (stock count, category ids / names,
    non-SGD currency, brand, shop_id) are intentionally absent: the
    Phase 1 spike proved they are not reachable from the shop-grid DOM,
    and the XHR path that would have carried them is blocked by
    Shopee's request-signing anti-bot. See
    docs/plans/2026-04-10-shopee-spike-notes.md for full reasoning.
    """

    item_id: int
    product_name: str
    product_url: str
    image_url: str | None = None
    price: float | None = None
    mrp: float | None = None  # original pre-discount list price
    currency: str = "SGD"
    discount_pct: int | None = None
    rating_star: float | None = None
    historical_sold_count: int | None = None
    is_sold_out: bool = False
    scraped_at: datetime
