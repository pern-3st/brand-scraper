"""Persistent-context launch for Lazada SG.

Mirrors ``shopee/_session.py`` — same patchright + persistent-profile
pattern. The Lazada spike found that shop pages don't gate behind a
login wall (verified on both campaign and non-campaign storefronts),
so navigation here is simpler than the Shopee equivalent.
"""
from __future__ import annotations

import errno
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from patchright.async_api import async_playwright

log = logging.getLogger(__name__)

# Resolve to backend/data/browser_profiles/lazada_sg. File layout:
#   backend/app/platforms/lazada/__init__.py
#   parents[0] = lazada/  parents[1] = platforms/
#   parents[2] = app/     parents[3] = backend/
BACKEND_ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = BACKEND_ROOT / "data" / "browser_profiles" / "lazada_sg"

# Files chrome writes into ``user_data_dir`` to claim exclusive ownership;
# can outlive the parent process and block the next launch_persistent_context
# (see shopee/_session.py for the longer treatment).
_SINGLETON_NAMES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


def clear_stale_singletons(profile_dir: Path) -> None:
    lock = profile_dir / "SingletonLock"
    if not lock.is_symlink():
        return
    try:
        target = os.readlink(lock)
    except OSError:
        return
    pid_str = target.rsplit("-", 1)[-1]
    try:
        pid = int(pid_str)
    except ValueError:
        return
    if _pid_alive(pid):
        return
    log.warning(
        "lazada: removing stale singleton lock (pid %d not alive) in %s",
        pid, profile_dir,
    )
    for name in _SINGLETON_NAMES:
        path = profile_dir / name
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("lazada: could not remove %s: %s", path, exc)


@asynccontextmanager
async def launch_persistent_context():
    """Open the persistent Chrome profile and yield ``(playwright, ctx)``."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    clear_stale_singletons(PROFILE_DIR)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 900},
        )
        try:
            yield p, ctx
        finally:
            await ctx.close()
