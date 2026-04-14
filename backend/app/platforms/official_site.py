from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator
from urllib.parse import urlparse

from browser_use import Agent, BrowserProfile, BrowserSession, ChatOpenAI
from dotenv import load_dotenv
from pydantic import BaseModel

from app import settings
from app.models import CategoryResult, OfficialSiteScrapeRequest
from app.platforms.base import ScrapeContext
from app.session import QueueLogHandler

load_dotenv()


class PriceExtractionResult(BaseModel):
    found: bool
    currency: str = ""
    prices: list[float] = []
    products_scanned: int = 0


async def _scrape_category(
    browser: BrowserSession,
    llm: ChatOpenAI,
    brand_url: str,
    section: str,
    category: str,
    max_products: int,
    cancel_event: asyncio.Event,
) -> tuple[CategoryResult, str]:
    """Scrape a single category and return the result plus detected currency."""
    section_hints = {
        "mens": 'adult men only — look for "Men" or "Menswear". Do NOT include boys or kids.',
        "womens": 'adult women only — look for "Women" or "Womenswear". Do NOT include girls or kids.',
        "kids": 'children only (boys and girls) — look for "Kids", "Children", "Boys", or "Girls". Do NOT include adult men or women.',
    }
    hint = section_hints.get(section, f'the "{section}" department')

    task = f"""You are collecting prices from a clothing website. Follow these steps exactly.

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
- Before collecting any prices, check the page URL and breadcrumbs.
- Confirm the page is specifically for the "{section}" section, not any other section.
- If the page shows mixed sections or a different section, go back and navigate correctly.

STEP 4 — COLLECT PRICES (up to {max_products} unique products)
- Scan the product listing page. For each product:
  - If it shows a strikethrough/original/"was"/"RRP" price, capture that original price.
  - Otherwise capture the displayed selling price.
- Track products by name or position to avoid duplicates. Each product should appear in your
  list only ONCE. If you scroll and see products you already recorded, skip them.
- Stop once you have {max_products} unique product prices.
- Do NOT keep scrolling or re-scanning after you have enough prices.

STEP 5 — RETURN RESULTS
- Return the list of unique prices, the currency symbol, found=true, and products_scanned
  equal to the number of unique products you collected.
"""

    async def should_stop() -> bool:
        return cancel_event.is_set()

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        output_model_schema=PriceExtractionResult,
        max_steps=30,
        max_failures=3,
        register_should_stop_callback=should_stop,
    )

    history = await agent.run()
    raw = history.final_result()

    if raw:
        result = PriceExtractionResult.model_validate_json(raw)
    else:
        result = PriceExtractionResult(found=False)

    if not result.found or not result.prices:
        return CategoryResult(
            category=category,
            status="not_found",
        ), result.currency

    return CategoryResult(
        category=category,
        status="found",
        lowest_price=min(result.prices),
        highest_price=max(result.prices),
        products_scanned=result.products_scanned or len(result.prices),
    ), result.currency


class OfficialSiteScraper:
    sse_event_name = "category_complete"
    platform_key = "official_site"

    def brand_slug(self, request: OfficialSiteScrapeRequest) -> str:
        return urlparse(str(request.brand_url)).netloc

    async def stream_products(
        self,
        request: OfficialSiteScrapeRequest,
        ctx: ScrapeContext,
    ) -> AsyncIterator[CategoryResult]:
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
                cat_result, _currency = await _scrape_category(
                    browser=browser,
                    llm=llm,
                    brand_url=str(request.brand_url),
                    section=request.section,
                    category=category,
                    max_products=request.max_products,
                    cancel_event=ctx.cancel_event,
                )
                yield cat_result
        finally:
            await browser.stop()
            bu_logger.removeHandler(handler)
