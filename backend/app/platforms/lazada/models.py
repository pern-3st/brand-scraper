from typing import Literal

from pydantic import BaseModel, HttpUrl


class LazadaScrapeRequest(BaseModel):
    platform: Literal["lazada"] = "lazada"
    # `/shop/<handle>/` — handle is accepted with or without trailing slash,
    # query, or fragment. Host must be lazada.sg (validated by the scraper).
    shop_url: HttpUrl
    max_products: int = 500
