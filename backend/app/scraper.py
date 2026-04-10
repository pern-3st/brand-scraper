import asyncio
import json
import logging
import os
from urllib.parse import urlparse

from browser_use import Agent, BrowserProfile, BrowserSession, ChatOpenAI
from dotenv import load_dotenv
from pydantic import BaseModel

from app.models import CategoryResult, ScrapeResponse
from app.session import QueueLogHandler, ScrapeSession

load_dotenv()


class PriceExtractionResult(BaseModel):
    found: bool
    currency: str = ""
    prices: list[float] = []
    products_scanned: int = 0


async def scrape_category(
    browser: BrowserSession,
    llm: ChatOpenAI,
    brand_url: str,
    section: str,
    category: str,
    max_products: int,
    cancel_event: asyncio.Event | None = None,
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
        return cancel_event is not None and cancel_event.is_set()

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


async def run_scrape_streaming(session: ScrapeSession) -> None:
    """Run the full scrape, emitting SSE events to session.queue."""
    request = session.request
    bu_logger = logging.getLogger("browser_use")
    handler = QueueLogHandler(session.queue)
    handler.setLevel(logging.INFO)
    bu_logger.addHandler(handler)

    try:
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-20250514")

        llm = ChatOpenAI(
            model=model,
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

        brand_url = str(request.brand_url)
        brand = urlparse(brand_url).netloc

        profile = BrowserProfile(headless=False, keep_alive=True, channel="chrome")
        browser = BrowserSession(browser_profile=profile)

        try:
            results: list[CategoryResult] = []
            detected_currency = "£"

            for category in request.categories:
                # Check for cancellation between categories
                if session.cancel_event.is_set():
                    session.queue.put_nowait({
                        "event": "cancelled",
                        "data": json.dumps(
                            ScrapeResponse(
                                brand=brand,
                                section=request.section,
                                currency=detected_currency,
                                results=results,
                            ).model_dump()
                        ),
                    })
                    return

                cat_result, currency = await scrape_category(
                    browser=browser,
                    llm=llm,
                    brand_url=brand_url,
                    section=request.section,
                    category=category,
                    max_products=request.max_products,
                    cancel_event=session.cancel_event,
                )
                if currency:
                    detected_currency = currency
                results.append(cat_result)

                session.queue.put_nowait({
                    "event": "category_complete",
                    "data": json.dumps(cat_result.model_dump()),
                })

            session.queue.put_nowait({
                "event": "done",
                "data": json.dumps(
                    ScrapeResponse(
                        brand=brand,
                        section=request.section,
                        currency=detected_currency,
                        results=results,
                    ).model_dump()
                ),
            })

        finally:
            await browser.stop()

    except Exception as e:
        session.queue.put_nowait({
            "event": "error",
            "data": json.dumps({"message": str(e)}),
        })

    finally:
        bu_logger.removeHandler(handler)
