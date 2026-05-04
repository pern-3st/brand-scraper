"""Shared persistent-context launch + login-wall handshake for Shopee.

Both ``ShopeeScraper`` (grid scraping) and the upcoming
``ShopeeEnrichment`` (per-product detail pass) reuse the patchright
profile at ``backend/data/browser_profiles/shopee_sg``. Without that
profile the very first navigation gets a login wall — so the
launch + login-wall recovery dance must be identical between the two
call sites.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from patchright.async_api import async_playwright

from app.platforms.base import ScrapeContext
from app.platforms.shopee.extract import GRID_CARD_SELECTOR

log = logging.getLogger(__name__)

# Resolve to backend/data/browser_profiles/shopee_sg. File layout:
#   backend/app/platforms/shopee/__init__.py
#   parents[0] = shopee/  parents[1] = platforms/
#   parents[2] = app/     parents[3] = backend/
BACKEND_ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = BACKEND_ROOT / "data" / "browser_profiles" / "shopee_sg"

CARD_WAIT_MS = 10_000


@asynccontextmanager
async def launch_persistent_context():
    """Open the persistent Chrome profile and yield ``(playwright, ctx)``.
    Cleans up the context on exit."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 900},
        )
        try:
            yield p, ctx
        finally:
            await ctx.close()


async def wait_for_cards(page, *, selector: str = GRID_CARD_SELECTOR) -> bool:
    """Wait for at least one ``selector`` element. True on success, False on timeout."""
    try:
        await page.wait_for_selector(selector, timeout=CARD_WAIT_MS)
        return True
    except Exception:
        return False


async def navigate_with_login_wall_recovery(
    page,
    url: str,
    ctx: ScrapeContext,
    *,
    ready_selector: str = GRID_CARD_SELECTOR,
    login_message: str = (
        "Log in to Shopee in the open Chrome window, then click Continue."
    ),
) -> bool:
    """Navigate ``page`` to ``url``, waiting for ``ready_selector``. If the
    selector never appears, assume Shopee redirected to a login wall:
    emit ``login_required``, await the user's login or a cancel, and
    retry the navigation once.

    Returns True if the page is ready, False if the run was cancelled
    during the login wait. Raises ``RuntimeError`` if the page is still
    not ready after a successful login signal.
    """
    await page.goto(url, wait_until="domcontentloaded")
    if await wait_for_cards(page, selector=ready_selector):
        return True

    log.info("shopee: no ready signal on first load — assuming login wall")
    ctx.queue.put_nowait({
        "event": "login_required",
        "data": json.dumps({"message": login_message}),
    })
    login_task = asyncio.create_task(ctx.login_event.wait())
    cancel_task = asyncio.create_task(ctx.cancel_event.wait())
    _, pending = await asyncio.wait(
        [login_task, cancel_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()
    if ctx.cancel_event.is_set():
        return False
    ctx.login_event.clear()

    await page.goto(url, wait_until="domcontentloaded")
    if not await wait_for_cards(page, selector=ready_selector):
        raise RuntimeError(
            f"shopee: still no ready signal at {url!r} after login. "
            "Check the URL or inspect the browser window."
        )
    return True
