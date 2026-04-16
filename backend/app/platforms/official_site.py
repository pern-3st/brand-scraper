from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator
from urllib.parse import urlparse

from browser_use import Agent, BrowserProfile, BrowserSession, ChatOpenAI
from dotenv import load_dotenv
from pydantic import BaseModel

from app import settings
from app.models import OfficialSiteScrapeRequest, ProductRecord
from app.platforms.base import ScrapeContext
from app.session import QueueLogHandler

load_dotenv()


class ProductExtraction(BaseModel):
    """A single product the agent extracted from a category listing."""
    name: str
    price: float | None = None           # visible selling price
    original_price: float | None = None  # strikethrough / "was" / RRP price
    url: str | None = None               # product detail page URL


class ProductExtractionResult(BaseModel):
    found: bool
    currency: str = ""
    products: list[ProductExtraction] = []


def _infer_discount_pct(price: float | None, mrp: float | None) -> int | None:
    if price is None or mrp is None or mrp <= 0 or mrp <= price:
        return None
    return int(round((mrp - price) / mrp * 100))


async def _scrape_category(
    browser: BrowserSession,
    llm: ChatOpenAI,
    brand_url: str,
    section: str,
    category: str,
    max_products: int,
    cancel_event: asyncio.Event,
) -> list[ProductRecord]:
    """Scrape a single category, returning a list of ProductRecords."""
    section_hints = {
        "mens": 'adult men only — look for "Men" or "Menswear". Do NOT include boys or kids.',
        "womens": 'adult women only — look for "Women" or "Womenswear". Do NOT include girls or kids.',
        "kids": 'children only (boys and girls) — look for "Kids", "Children", "Boys", or "Girls". Do NOT include adult men or women.',
    }
    hint = section_hints.get(section, f'the "{section}" department')

    task = f"""You are collecting product listings from a clothing website. Follow these steps exactly.

STEP 1 — NAVIGATE VIA MENUS (mandatory)
- Go to {brand_url}
- Locate the site's top navigation bar or hamburger menu.
- You need the "{section}" section: {hint}
- Click the matching link in the navigation menu.
- Do NOT use the search bar. Do NOT type into any search field. Only use navigation menus and links.

STEP 2 — FIND THE CATEGORY
- Within the {section} section, find the "{category}" subcategory (or the closest match).
- If the site shows a flyout/dropdown menu with subcategories, click the matching one.
- If you cannot find this category after exploring the {section} navigation, return found=false immediately.

STEP 3 — VERIFY YOU ARE IN THE CORRECT SECTION
- Before collecting products, check the page URL and breadcrumbs.
- Confirm the page is specifically for the "{section}" section, not any other section.
- If the page shows mixed sections or a different section, go back and navigate correctly.

STEP 4 — COLLECT PRODUCTS (up to {max_products} unique products)
- Scan the product listing page. For each product, capture:
  - name: the product's display name
  - price: the visible selling price (what you'd actually pay today)
  - original_price: if the product shows a strikethrough / "was" / "RRP" price,
    capture that value here. Otherwise leave original_price null.
  - url: the product detail page link if available (absolute or relative)
- Track products by name to avoid duplicates. Each product should appear in your
  list only ONCE. If you scroll and see products you already recorded, skip them.
- Stop once you have {max_products} unique products.
- Do NOT keep scrolling or re-scanning after you have enough products.

STEP 5 — RETURN RESULTS
- Return the list of unique products, the currency symbol, and found=true.
- If you could not locate any products (empty listing page), return found=false.
"""

    async def should_stop() -> bool:
        return cancel_event.is_set()

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        output_model_schema=ProductExtractionResult,
        max_steps=30,
        max_failures=3,
        register_should_stop_callback=should_stop,
    )

    history = await agent.run()
    raw = history.final_result()

    if raw:
        result = ProductExtractionResult.model_validate_json(raw)
    else:
        result = ProductExtractionResult(found=False)

    if not result.found or not result.products:
        return []

    now = datetime.now(timezone.utc)
    records: list[ProductRecord] = []
    for p in result.products:
        records.append(ProductRecord(
            product_name=p.name,
            product_url=p.url,
            price=p.price,
            mrp=p.original_price,
            currency=result.currency,
            discount_pct=_infer_discount_pct(p.price, p.original_price),
            category=category,
            scraped_at=now,
        ))
    return records


class OfficialSiteScraper:
    sse_event_name = "product"
    platform_key = "official_site"

    def brand_slug(self, request: OfficialSiteScrapeRequest) -> str:
        return urlparse(str(request.brand_url)).netloc

    async def stream_products(
        self,
        request: OfficialSiteScrapeRequest,
        ctx: ScrapeContext,
    ) -> AsyncIterator[ProductRecord]:
        bu_logger = logging.getLogger("browser_use")
        handler = QueueLogHandler(ctx.queue)
        handler.setLevel(logging.INFO)
        bu_logger.addHandler(handler)

        effective = settings.load()
        api_key = effective["openrouter_api_key"]
        model = effective["openrouter_model"]
        if not api_key:
            raise RuntimeError(
                "OpenRouter API key is not configured. Open the dashboard settings "
                "(gear icon) and paste your key, or set OPENROUTER_API_KEY in the "
                "environment."
            )
        llm = ChatOpenAI(
            model=model,
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

        profile = BrowserProfile(headless=False, keep_alive=True, channel="chrome")
        browser = BrowserSession(browser_profile=profile)

        try:
            for category in request.categories:
                if ctx.cancel_event.is_set():
                    return
                records = await _scrape_category(
                    browser=browser,
                    llm=llm,
                    brand_url=str(request.brand_url),
                    section=request.section,
                    category=category,
                    max_products=request.max_products,
                    cancel_event=ctx.cancel_event,
                )
                for record in records:
                    if ctx.cancel_event.is_set():
                        return
                    yield record
        finally:
            await browser.stop()
            bu_logger.removeHandler(handler)
