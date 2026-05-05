from typing import Literal

from pydantic import BaseModel, HttpUrl


class ShopeeScrapeRequest(BaseModel):
    platform: Literal["shopee"] = "shopee"
    shop_url: HttpUrl
    max_products: int = 500
