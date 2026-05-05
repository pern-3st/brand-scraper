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
import errno
import json
import logging
import os
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

# Files chrome writes into ``user_data_dir`` to claim exclusive ownership.
# SingletonLock is a symlink whose target encodes "<hostname>-<pid>"; the
# other two are sockets/cookies that pair with it. If the previous chrome
# died abruptly (manual window close on macOS leaves helpers running, or
# the parent python was SIGKILLed), these can outlive the process and
# block the next ``launch_persistent_context`` with a profile-in-use error.
_SINGLETON_NAMES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


def clear_stale_singletons(profile_dir: Path) -> None:
    """Remove SingletonLock/Cookie/Socket if the PID encoded in
    SingletonLock is no longer alive. Safe no-op when the profile is
    actively in use by a live chrome process."""
    lock = profile_dir / "SingletonLock"
    if not lock.is_symlink():
        return
    try:
        target = os.readlink(lock)
    except OSError:
        return
    # Target format: "<hostname>-<pid>"
    pid_str = target.rsplit("-", 1)[-1]
    try:
        pid = int(pid_str)
    except ValueError:
        return
    if _pid_alive(pid):
        return
    log.warning(
        "shopee: removing stale singleton lock (pid %d not alive) in %s",
        pid, profile_dir,
    )
    for name in _SINGLETON_NAMES:
        path = profile_dir / name
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("shopee: could not remove %s: %s", path, exc)


@asynccontextmanager
async def launch_persistent_context():
    """Open the persistent Chrome profile and yield ``(playwright, ctx)``.
    Cleans up the context on exit."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    clear_stale_singletons(PROFILE_DIR)
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
