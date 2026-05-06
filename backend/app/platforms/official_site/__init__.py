from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from browser_use import Agent, BrowserSession, ChatOpenAI
from browser_use.tools.service import Tools
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from app.models import OfficialSiteProductRecord, OfficialSiteScrapeRequest
from app.platforms._browser_use import (
    FALLBACK_MODEL,
    SanitizedChatOpenAI,
    _cap_tab_runs,
    _compile_extraction_schema,
    _flatten_nullable_any_of,
    _get_extract_fs,
    _get_tools,
    _sanitize_message_content,
    build_browser_profile,
    build_llm,
    canonical_url,
    extract_structured,
)
from app.platforms.base import ScrapeContext

load_dotenv()

logger = logging.getLogger(__name__)


# Re-exports kept for backwards compatibility with tests / external callers
# that imported these symbols from this module before they moved to
# ``app.platforms._browser_use``.
__all__ = [
    "FALLBACK_MODEL",
    "SanitizedChatOpenAI",
    "_cap_tab_runs",
    "_compile_extraction_schema",
    "_flatten_nullable_any_of",
    "_get_extract_fs",
    "_get_tools",
    "_sanitize_message_content",
    "canonical_url",
    "EXTRACTION_SCHEMA",
    "PageExtraction",
    "ProductExtraction",
    "Pagination",
    "PageResult",
    "NavResult",
    "OfficialSiteScraper",
]


class ProductExtraction(BaseModel):
    """A single product the agent extracted from a category listing."""
    name: str
    price: float | None = None           # visible selling price
    original_price: float | None = None  # strikethrough / "was" / RRP price
    url: str | None = None               # product detail page URL
    image_url: str | None = None         # product thumbnail image URL
    is_sold_out: bool = False            # true if the card shows sold-out / out-of-stock


class PageExtraction(BaseModel):
    """Schema the `extract` tool fills per listing page.

    Passed to the Agent as `extraction_schema` (after inlining) so each
    `extract` call returns structured product data, not free-text markdown.
    """
    found: bool
    currency: str = ""
    products: list[ProductExtraction] = []


class NavResult(BaseModel):
    """Final `done` payload for the navigator agent.

    `landed_url` is the URL the agent believes it finished on, copied from
    its DOM observation. It exists so the orchestrator can cross-check the
    LLM's claim against the browser's actual URL before trusting `found=true`
    — catches cases where the agent confabulates its location.
    """
    found: bool
    landed_url: str = ""


class Pagination(BaseModel):
    """How to advance from the current listing page to the next one."""
    mechanism: Literal["url_param", "next_button", "load_more", "infinite_scroll", "end"]
    url_pattern: str | None = None  # e.g. "?page={n}" — only set when mechanism=="url_param"


class PageResult(BaseModel):
    """Final `done` payload for a per-page extraction agent."""
    currency: str = ""      # currency symbol seen on this page
    pagination: Pagination


EXTRACTION_SCHEMA = _compile_extraction_schema(PageExtraction.model_json_schema())


def _build_page_hint(page_index: int, previous: Pagination | None) -> str:
    """Synthesize a one-line hint for the next page agent based on how the
    previous page advanced. Keeps per-page task prompts bounded."""
    if page_index <= 1 or previous is None:
        return ""
    if previous.mechanism == "url_param" and previous.url_pattern:
        target = previous.url_pattern.replace("{n}", str(page_index))
        return (
            f"HINT: previous page advanced via URL pattern `{previous.url_pattern}`. "
            f"Navigate directly to `{target}` relative to the current URL. "
            f"If that fails, look for a Next/Load-more control."
        )
    if previous.mechanism == "next_button":
        return "HINT: previous page advanced via a 'Next' button — look for it first."
    if previous.mechanism == "load_more":
        return "HINT: previous page advanced via a 'Load more' button — click it to reveal more products."
    if previous.mechanism == "infinite_scroll":
        return "HINT: previous page advanced via infinite scroll — scroll to the bottom to load more."
    return ""


def _nav_guidelines(section: str, category: str) -> str:
    """General reasoning/anti-loop guidance shared by both nav prompts.

    Kept brand-agnostic: no site-specific layout assumptions, no named
    elements. The rules describe *how to decide*, not *what to click*.
    """
    return f"""GENERAL GUIDELINES
- Classify the current page at every step; don't gate on exact URL matches:
  (a) the page already shows a product listing for "{category}" → return done, found=true.
  (b) the page exposes a link, tile, flyout item, or menu entry whose text matches "{category}" or a close synonym → click it.
  (c) no plausible path to "{category}" from here → return done, found=false.
  URL slugs and breadcrumbs are signals, not requirements. A site may route to the correct listing under a different slug, a localized path, or without updating breadcrumbs.
- The interactive-elements list is the source of truth for what's on the page. The screenshot only shows the current viewport; relevant links are often off-screen but already present in the element list. If the list contains a link whose text matches "{section}" or "{category}", act on it — do not wait for it to appear on screen.
- Do not call `wait` or re-navigate to the same URL twice in a row. If an action leaves the page visibly unchanged, treat the DOM as final: scroll, try a different link in the element list, or return found=false. Two consecutive `wait`s — or repeated navigations to the same URL — mean you are stuck; break the loop by choosing a different action."""


def _build_nav_task(brand_url: str, section: str, category: str) -> str:
    section_hints = {
        "mens": 'adult men only — look for "Men" or "Menswear". Do NOT include boys or kids.',
        "womens": 'adult women only — look for "Women" or "Womenswear". Do NOT include girls or kids.',
        "kids": 'children only (boys and girls) — look for "Kids", "Children", "Boys", or "Girls". Do NOT include adult men or women.',
    }
    hint = section_hints.get(section, f'the "{section}" department')
    return f"""You are reaching a product listing page on a clothing site. Do NOT extract products yet — another agent will do that.

STEP 1 — NAVIGATE VIA MENUS
- Go to {brand_url}
- Locate the site's top navigation bar or hamburger menu.
- You need the "{section}" section: {hint}
- Click the matching link. Do NOT use the search bar.

STEP 2 — FIND THE CATEGORY
- Within the {section} section, find the "{category}" subcategory (or the closest match).
- If a flyout shows subcategories, click the matching one.
- Do NOT use `search_page` during navigation — it dumps hundreds of matches and truncates output.
- If you cannot find this category after exploring the {section} navigation, return found=false immediately.

STEP 3 — VERIFY
- Check the URL and breadcrumbs confirm you are in the "{section}" section.
- If mixed or wrong, navigate correctly before returning.

STEP 4 — FINISH
- Return `done` with found=true if you reached a listing page for "{section}" / "{category}", or found=false otherwise.
- Set `landed_url` to the URL shown in the browser right now, copied verbatim. Do NOT guess — read it from the current page state.
- Do NOT extract products. Another agent will do that on this URL.
- Keep thinking and memory to one short sentence each.

{_nav_guidelines(section, category)}
"""


def _build_direct_nav_task(brand_url: str, section: str, category: str) -> str:
    """Nav prompt for the `skip_menu_navigation` mode.

    Assumes `brand_url` already points inside the target section (e.g. a
    section hub like `/kids.html`, or even the final listing). Agent
    short-circuits to found=true if the current URL/breadcrumbs already
    match the requested `category`; otherwise it only uses in-page
    subcategory links — never the top nav, hamburger, or search bar.
    """
    return f"""You are reaching a product listing page on a clothing site. Do NOT extract products yet — another agent will do that.

STEP 1 — START
- Go to {brand_url}. This URL should already be inside the "{section}" area of the site.

STEP 2 — CHECK FIRST
- Look at the URL, page heading, and breadcrumbs.
- If they already indicate "{section}" / "{category}" (or the page already shows a grid of "{category}" products), return `done` with found=true IMMEDIATELY. Do NOT click anything else.

STEP 3 — OTHERWISE, NARROW DOWN
- If you are on a section hub page that lists subcategories, find and click the "{category}" subcategory (or closest match).
- Use only in-page subcategory links. Do NOT open the top navigation, hamburger menu, or any global menu.
- Do NOT use `search_page` or the site's search bar.
- If you cannot find "{category}" after one or two clicks from here, return found=false.

STEP 4 — VERIFY
- Check the URL and breadcrumbs confirm you are inside "{section}".

STEP 5 — FINISH
- Return `done` with found=true if you reached a listing page for "{section}" / "{category}", or found=false otherwise.
- Set `landed_url` to the URL shown in the browser right now, copied verbatim. Do NOT guess — read it from the current page state.
- Do NOT extract products. Another agent will do that on this URL.
- Keep thinking and memory to one short sentence each.

{_nav_guidelines(section, category)}
"""


MAX_STEPS_PER_PAGE = 15

# Agent-level timeouts. Defaults (llm_timeout auto-detected ~75s,
# step_timeout 180s) were tight for dense retail listing pages — the primary
# routinely failed the 75s budget while still mid-response. Raising the LLM
# budget lets a slow-but-successful primary win; raising the step budget
# accommodates `llm_timeout` + action execution within a single step.
_LLM_TIMEOUT_SECONDS = 180
_STEP_TIMEOUT_SECONDS = 300


def _build_page_task(*, page_index: int, hint: str) -> str:
    hint_block = (hint + "\n\n") if hint else ""
    return f"""{hint_block}You are on a product listing page (page {page_index}). Extract the products on this page, then advance to the next page.

STEP 1 — EXTRACT
- Call the `extract` tool once with `extract_links=true`.
- Query must name these fields: name, price, original_price, url, image_url, is_sold_out.
  - name: display name
  - price: visible selling price
  - original_price: strikethrough / "was" / RRP, else null
  - url: product detail page link (absolute or relative)
  - image_url: thumbnail src on the listing card
  - is_sold_out: true if the card clearly shows sold-out / out-of-stock
- Only single items — skip multi-packs, bundles, gift sets, kits (e.g. "3-pack", "Pack of 5", "Bundle of 2", "Set of 3").
- If the grid is lazy-loaded, scroll once before extracting.
- Do NOT use `evaluate` (JS) or persist to files. Your extract result is the source of truth.

STEP 2 — REPORT PAGINATION
- Numbered page links ("Go to page 2", "1 2 3 … N") → mechanism="url_param". Read the href of the page-2 link with ONE `find_elements` call using `attributes=["href"]`, then derive url_pattern by replacing the page-2 value with `{{n}}`. Common templates: `?page={{n}}`, `?p={{n}}`, `/page/{{n}}`, `?start={{n}}`. Do NOT navigate — the orchestrator advances.
  - `find_elements` returns each element as `[idx] <tag> "text" {{attr="value"}}`. Read the href value from inside the braces. If you don't see `href="…"` in the result, you already have it — do NOT re-call the tool; just use what was returned.
  - If after ONE attempt you still can't derive a pattern, fall back to url_pattern="?page={{n}}" and still report mechanism="url_param".
- Infinite scroll (new products load on scroll with no button and no numbered links) → mechanism="infinite_scroll". Do NOT scroll further — the orchestrator advances.
- "Next" button only, no numbered links → click it once; mechanism="next_button".
- "Load more" button only, no numbered links → click it once; mechanism="load_more".
- No pagination / no new products after attempting → mechanism="end".
- When numbered links coexist with a "Load more" / "Next" button, prefer `url_param` — numbered links are the authoritative signal.
- Attempt at most ONE advance click. Don't re-extract after advancing.

STEP 3 — FINISH
- Return `done` with currency (the symbol on this page, or "") and pagination {{mechanism, url_pattern}}.
- Keep thinking and memory to one short sentence each.
- Hard cap: {MAX_STEPS_PER_PAGE} steps. If you reach step {MAX_STEPS_PER_PAGE - 3} without a successful extract, return mechanism="end".
"""


def _infer_discount_pct(price: float | None, mrp: float | None) -> int | None:
    if price is None or mrp is None or mrp <= 0 or mrp <= price:
        return None
    return int(round((mrp - price) / mrp * 100))


async def _navigate_to_category(
    *,
    browser: BrowserSession,
    llm: ChatOpenAI,
    brand_url: str,
    section: str,
    category: str,
    cancel_event: asyncio.Event,
    skip_menu_navigation: bool = False,
) -> NavResult:
    task = (
        _build_direct_nav_task(brand_url, section, category)
        if skip_menu_navigation
        else _build_nav_task(brand_url, section, category)
    )

    async def should_stop() -> bool:
        return cancel_event.is_set()

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        tools=_build_agent_tools(),
        output_model_schema=NavResult,
        max_failures=4,
        register_should_stop_callback=should_stop,
        use_thinking=False,
        llm_timeout=_LLM_TIMEOUT_SECONDS,
        step_timeout=_STEP_TIMEOUT_SECONDS,
    )
    history = await agent.run(max_steps=25)
    final = history.final_result()
    nav = NavResult(found=False)
    if final:
        try:
            nav = NavResult.model_validate_json(final)
        except ValidationError:
            return NavResult(found=False)

    if nav.found and nav.landed_url:
        try:
            actual_url = await browser.get_current_page_url()
        except Exception:
            actual_url = ""
        if actual_url and canonical_url(nav.landed_url) != canonical_url(actual_url):
            logger.warning(
                "nav agent reported landed_url=%r but browser is on %r — "
                "treating as not found (agent likely hallucinated navigation)",
                nav.landed_url, actual_url,
            )
            return NavResult(found=False, landed_url=actual_url)
    return nav


async def _extract_page(
    *,
    browser: BrowserSession,
    llm: ChatOpenAI,
    page_index: int,
    previous_pagination: Pagination | None,
    cancel_event: asyncio.Event,
) -> tuple[PageResult, list[ProductExtraction]]:
    """Run one per-page agent. Returns (page_result, products) where
    products are pulled directly from the agent's extract tool history —
    no JSONL file, no LLM transcription loop."""
    hint = _build_page_hint(page_index, previous_pagination)
    task = _build_page_task(page_index=page_index, hint=hint)

    async def should_stop() -> bool:
        return cancel_event.is_set()

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        tools=_build_agent_tools(),
        extraction_schema=EXTRACTION_SCHEMA,
        output_model_schema=PageResult,
        max_failures=4,
        register_should_stop_callback=should_stop,
        use_thinking=False,
        llm_timeout=_LLM_TIMEOUT_SECONDS,
        step_timeout=_STEP_TIMEOUT_SECONDS,
    )
    history = await agent.run(max_steps=MAX_STEPS_PER_PAGE)

    products: list[ProductExtraction] = []
    for extraction in _extractions_from_history(history):
        products.extend(extraction.products)

    final = history.final_result()
    if final:
        try:
            return PageResult.model_validate_json(final), products
        except ValidationError:
            pass
    return PageResult(pagination=Pagination(mechanism="end")), products


def _build_agent_tools() -> Tools:
    """Fresh Tools instance whose `click` action reports whether the click
    actually changed the URL.

    The default click action (browser_use/tools/service.py:611-672) returns
    `ActionResult(extracted_content='Clicked X')` as long as the CDP click
    event dispatches without raising — with no signal for whether the page
    state transitioned. When a click lands on a stale element, hits an
    anti-bot trap, or fires against a CDP session mid-reconnect (we've seen
    `Received duplicate response` warnings around the failure), the tool
    still reports success and the navigator LLM has nothing to distinguish
    "moved to subcategory" from "still on mixed listing." Because retail
    listing pages look superficially similar before and after a subcategory
    click (same nav, same product cards), the LLM frequently hallucinates
    `done: found=true`.

    This wrapper appends one of:
        `| URL: <before> → <after>`   (navigation occurred)
        `| URL unchanged: <url>`      (click dispatched, page stayed)
    to the ActionResult's `extracted_content`. The LLM then has explicit
    evidence in its history instead of inferring from visuals.

    We can't share one Tools across agents because `Agent.__init__` mutates
    the instance (e.g. `use_structured_output_action` rewrites the `done`
    schema per-agent — see browser_use/agent/service.py:359), so callers
    must build a fresh Tools per Agent.
    """
    tools = Tools()
    # _register_click_action (tools/service.py:1978) creates a `click`
    # that looks up `self._click_by_index` at call time, so replacing
    # the attribute is enough — no need to re-register, and it survives
    # any later `set_coordinate_clicking` toggling by the Agent.
    tools._click_by_index = _wrap_click_with_url_check(tools._click_by_index)
    return tools


def _wrap_click_with_url_check(original_click):
    """Factory for the URL-aware click wrapper. Extracted so the annotation
    logic can be exercised without instantiating a real Tools (whose init
    touches the full action registry)."""

    async def click_with_url_check(params, browser_session):
        try:
            url_before = await browser_session.get_current_page_url()
        except Exception:
            url_before = None

        result = await original_click(params, browser_session)

        try:
            url_after = await browser_session.get_current_page_url()
        except Exception:
            url_after = None

        existing = getattr(result, "extracted_content", None)
        if existing and url_before is not None and url_after is not None:
            if url_before == url_after:
                annotation = f" | URL unchanged: {url_before}"
            else:
                annotation = f" | URL: {url_before} → {url_after}"
            result.extracted_content = existing + annotation

        return result

    return click_with_url_check


# Wait budget for lazy-loaded content after a scroll. A single scrollTo
# fires the IntersectionObserver but cards paint asynchronously; extracting
# immediately sees the same DOM as before the scroll.
_SCROLL_POLL_INTERVAL = 0.5
_SCROLL_MAX_WAIT = 4.0
_SCROLL_ITERATIONS = 3

# Wait budget for client-rendered listing content after a navigation. Retail
# SPAs (H&M, Zara, etc.) return a skeleton DOM on navigate_to and paint the
# product grid 1–4s later, so extracting immediately produces zero products.
# Polls `<a href>` count — a cheap, site-agnostic proxy for card density —
# until the count stabilises for two consecutive polls, or the budget elapses.
_NAV_POLL_INTERVAL = 0.5
_NAV_MAX_WAIT = 8.0
_NAV_STABLE_POLLS = 2


_DETERMINISTIC_MECHANISMS = {"url_param", "infinite_scroll"}


_EXTRACT_QUERY = (
    "Extract all individual single-unit products on this listing page. "
    "For each: name, price, original_price (strikethrough/was/RRP else null), "
    "url (product detail link), image_url (thumbnail src), is_sold_out "
    "(true if the card clearly shows sold-out). Skip multi-packs, bundles, "
    "gift sets, and kits (e.g. '3-pack', 'Set of 2')."
)


async def _invoke_extract_tool(
    *,
    browser: BrowserSession,
    llm: ChatOpenAI,
    query: str,
) -> PageExtraction:
    """Compat wrapper around ``extract_structured`` for the grid scraper's
    deterministic path. Returns an empty ``PageExtraction`` on hard
    failure so callers can treat it as a zero-yield page."""
    result = await extract_structured(
        browser=browser, llm=llm, schema=PageExtraction, query=query,
    )
    if result is None:
        return PageExtraction(found=False)
    return result  # type: ignore[return-value]


def _advance_url_param(current_url: str, url_pattern: str, next_page_index: int) -> str:
    """Compose the next-page URL from the current URL and a `?page={n}`-style
    pattern. Replaces any existing occurrence of the pattern's key, or
    appends it."""
    target = url_pattern.replace("{n}", str(next_page_index))
    if not target.startswith("?"):
        return current_url.split("#", 1)[0] + target
    new_pairs = parse_qsl(target.lstrip("?"), keep_blank_values=True)
    parts = urlsplit(current_url)
    override_keys = {k for k, _ in new_pairs}
    existing = [
        (k, v) for (k, v) in parse_qsl(parts.query, keep_blank_values=True)
        if k not in override_keys
    ]
    merged = urlencode(existing + new_pairs)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, merged, ""))


async def _wait_for_listing_ready(page) -> None:
    """Poll `<a href>` count after a navigation until it holds steady for
    `_NAV_STABLE_POLLS` consecutive polls, or the wait budget elapses.

    Without this, the deterministic path extracts against a skeleton DOM on
    SPA listings and produces zero products, which used to force the run
    to terminate on page 2.
    """
    last = -1
    stable = 0
    waited = 0.0
    while waited < _NAV_MAX_WAIT:
        try:
            current = int(await page.evaluate("() => document.querySelectorAll('a[href]').length"))
        except Exception:
            return
        if current > 0 and current == last:
            stable += 1
            if stable >= _NAV_STABLE_POLLS:
                return
        else:
            stable = 0
        last = current
        await asyncio.sleep(_NAV_POLL_INTERVAL)
        waited += _NAV_POLL_INTERVAL


async def _scroll_and_wait_for_new_content(page) -> None:
    """Scroll to bottom, then poll the link count until it stops growing or
    we hit the wait budget. Approximates one 'page' of infinite-scroll
    content by scrolling up to _SCROLL_ITERATIONS times.

    Counts `<a href>` elements as a cheap, site-agnostic proxy for card
    density. Real product cards are a subset, but the *delta* on scroll is
    the signal we care about."""
    async def count_links() -> int:
        try:
            raw = await page.evaluate("() => document.querySelectorAll('a[href]').length")
            return int(raw)
        except Exception:
            return 0

    for _ in range(_SCROLL_ITERATIONS):
        before = await count_links()
        await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        waited = 0.0
        grew = False
        while waited < _SCROLL_MAX_WAIT:
            await asyncio.sleep(_SCROLL_POLL_INTERVAL)
            waited += _SCROLL_POLL_INTERVAL
            after = await count_links()
            if after > before:
                grew = True
                break
        if not grew:
            return


async def _extract_page_deterministic(
    *,
    browser: BrowserSession,
    llm: ChatOpenAI,
    page_index: int,
    previous_pagination: Pagination,
    cancel_event: asyncio.Event,
) -> tuple[PageResult, list[ProductExtraction]]:
    """Handle `url_param` and `infinite_scroll` pages without an Agent.
    Navigates (waiting for the listing to paint) or scrolls, invokes the
    extract tool once, and returns the same shape as `_extract_page`.

    Propagates the same mechanism forward even when the extract yields zero
    products — the orchestrator's `zero_yield_streak` is the authoritative
    terminator, so a single flaky render (e.g. extract firing against a
    skeleton DOM) doesn't kill the whole multi-page run.
    """
    if cancel_event.is_set():
        return PageResult(pagination=Pagination(mechanism="end")), []

    mech = previous_pagination.mechanism
    if mech == "url_param" and previous_pagination.url_pattern:
        current_url = await browser.get_current_page_url()
        next_url = _advance_url_param(current_url, previous_pagination.url_pattern, page_index)
        await browser.navigate_to(next_url)
        page = await browser.get_current_page()
        await _wait_for_listing_ready(page)
    elif mech == "infinite_scroll":
        page = await browser.get_current_page()
        await _scroll_and_wait_for_new_content(page)
    else:
        raise ValueError(f"_extract_page_deterministic cannot handle mechanism={mech!r}")

    extraction = await _invoke_extract_tool(browser=browser, llm=llm, query=_EXTRACT_QUERY)
    products = list(extraction.products)

    next_pagination = Pagination(
        mechanism=mech,
        url_pattern=previous_pagination.url_pattern if mech == "url_param" else None,
    )
    return (
        PageResult(currency=extraction.currency, pagination=next_pagination),
        products,
    )


async def _scrape_category(
    browser: BrowserSession,
    llm: ChatOpenAI,
    brand_url: str,
    section: str,
    category: str,
    max_products: int,
    cancel_event: asyncio.Event,
    skip_menu_navigation: bool = False,
) -> list[OfficialSiteProductRecord]:
    """Drive a navigator agent + a loop of per-page agents to collect up to
    `max_products` items from one category. See
    docs/plans/2026-04-23-per-page-agent-orchestration.md for rationale."""
    nav = await _navigate_to_category(
        browser=browser,
        llm=llm,
        brand_url=brand_url,
        section=section,
        category=category,
        cancel_event=cancel_event,
        skip_menu_navigation=skip_menu_navigation,
    )
    if not nav.found or cancel_event.is_set():
        return []

    all_products: list[ProductExtraction] = []
    seen_urls: set[str] = set()
    currency = ""
    previous_pagination: Pagination | None = None
    page_index = 0
    zero_yield_streak = 0

    # Loop runs until budget met, pagination ends, zero-yield guard trips, or cancel.
    # Budget is measured in unique URLs (not raw extractions) so duplicate pages
    # can't satisfy it. Two consecutive zero-yield pages break the loop as a
    # defence against silent agent failures masquerading as "end".
    while not cancel_event.is_set() and len(seen_urls) < max_products:
        page_index += 1
        if (
            previous_pagination is not None
            and previous_pagination.mechanism in _DETERMINISTIC_MECHANISMS
        ):
            page_result, page_products = await _extract_page_deterministic(
                browser=browser,
                llm=llm,
                page_index=page_index,
                previous_pagination=previous_pagination,
                cancel_event=cancel_event,
            )
        else:
            page_result, page_products = await _extract_page(
                browser=browser,
                llm=llm,
                page_index=page_index,
                previous_pagination=previous_pagination,
                cancel_event=cancel_event,
            )

        new_unique = 0
        for p in page_products:
            key = canonical_url(p.url, base=brand_url)
            if key and key not in seen_urls:
                seen_urls.add(key)
                new_unique += 1
        all_products.extend(page_products)
        if page_result.currency and not currency:
            currency = page_result.currency

        logger.info(
            "official_site page %d: parsed=%d new_unique=%d mechanism=%s total=%d/%d",
            page_index, len(page_products), new_unique,
            page_result.pagination.mechanism, len(seen_urls), max_products,
        )

        if page_result.pagination.mechanism == "end":
            if len(seen_urls) < max_products:
                logger.warning(
                    "official_site ended early after %d pages: total=%d/%d — "
                    "may indicate silent per-page agent failure",
                    page_index, len(seen_urls), max_products,
                )
            break

        if new_unique == 0:
            zero_yield_streak += 1
            if zero_yield_streak >= 2:
                logger.warning(
                    "official_site stopping after %d consecutive zero-yield pages — "
                    "pagination may be stuck or agent failing silently",
                    zero_yield_streak,
                )
                break
        else:
            zero_yield_streak = 0

        previous_pagination = page_result.pagination

    products = _dedupe_by_url(all_products, base=brand_url)
    if not products:
        return []

    now = datetime.now(timezone.utc)
    return [
        OfficialSiteProductRecord(
            product_name=p.name,
            product_url=p.url,
            image_url=p.image_url,
            price=p.price,
            mrp=p.original_price,
            currency=currency,
            discount_pct=_infer_discount_pct(p.price, p.original_price),
            is_sold_out=p.is_sold_out,
            category=category,
            scraped_at=now,
        )
        for p in products
    ]


def _extractions_from_history(history) -> list[PageExtraction]:
    """Walk an AgentHistoryList and return every structured `extract`
    payload as a PageExtraction. Relies on browser_use's convention of
    stashing structured extractions in `ActionResult.metadata
    ['extraction_result']['data']` as a pre-parsed dict matching
    EXTRACTION_SCHEMA. Malformed payloads are skipped with a warning —
    partial results beat a failed run.
    """
    out: list[PageExtraction] = []
    for step in getattr(history, "history", []):
        for result in getattr(step, "result", []) or []:
            meta = getattr(result, "metadata", None)
            if not isinstance(meta, dict):
                continue
            extraction = meta.get("extraction_result")
            if not isinstance(extraction, dict):
                continue
            data = extraction.get("data")
            if not isinstance(data, dict):
                continue
            try:
                out.append(PageExtraction.model_validate(data))
            except ValidationError as exc:
                logger.warning("skipping malformed extraction payload: %s", exc)
    return out


def _dedupe_by_url(
    products: list[ProductExtraction],
    *,
    base: str | None = None,
) -> list[ProductExtraction]:
    """Filter to unique products keyed on canonicalized URL, and rewrite each
    kept record's `url` to the canonical (absolute) form so downstream
    consumers don't have to re-resolve relative paths. Records with no URL
    (or an unparseable one) are dropped — they can't be actioned downstream
    and can't be safely deduplicated. First occurrence wins. `base` resolves
    relative URLs (e.g. `/en_sg/productpage.X.html`) against the listing
    origin. Logs a single-line summary at INFO when given any input, for run
    observability."""
    seen: set[str] = set()
    out: list[ProductExtraction] = []
    dropped_no_url = 0
    dropped_duplicate = 0
    for p in products:
        key = canonical_url(p.url, base=base)
        if not key:
            dropped_no_url += 1
            continue
        if key in seen:
            dropped_duplicate += 1
            continue
        seen.add(key)
        out.append(p.model_copy(update={"url": key}))
    if products:
        logger.info(
            "official_site dedupe: kept=%d duplicates=%d no_url=%d",
            len(out), dropped_duplicate, dropped_no_url,
        )
    return out


class OfficialSiteScraper:
    sse_event_name = "product"
    platform_key = "official_site"

    def brand_slug(self, request: OfficialSiteScrapeRequest) -> str:
        return urlparse(str(request.brand_url)).netloc

    async def stream_products(
        self,
        request: OfficialSiteScrapeRequest,
        ctx: ScrapeContext,
    ) -> AsyncIterator[OfficialSiteProductRecord]:
        llm = build_llm()
        browser = BrowserSession(browser_profile=build_browser_profile())

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
                    skip_menu_navigation=request.skip_menu_navigation,
                )
                for record in records:
                    if ctx.cancel_event.is_set():
                        return
                    yield record
        finally:
            await browser.stop()
