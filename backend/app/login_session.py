"""Singleton interactive Shopee-login session driven from the Settings UI.

The user opens a Chrome window pointed at shopee.sg, signs in, and either:
  - clicks "Close" in the UI → ``close()`` resolves the close event, the
    background task exits ``async with launch_persistent_context()``, and
    patchright cleanly tears down chrome (releasing the SingletonLock).
  - closes the chrome window manually → ``context.on('close', ...)``
    fires, the same close event is set, and we still do the proper
    ``ctx.close()`` so no zombie helpers / stale lock are left behind.

Only one login session can exist at a time. The session also mutexes
with shopee scrape sessions, since both share the same persistent
profile dir.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.platforms.shopee._session import PROFILE_DIR, launch_persistent_context

log = logging.getLogger(__name__)


@dataclass
class _LoginSession:
    task: asyncio.Task | None = None
    close_event: asyncio.Event = field(default_factory=asyncio.Event)
    opened_at: str = ""
    error: str | None = None


_session: _LoginSession | None = None


def _is_running(sess: _LoginSession | None) -> bool:
    return sess is not None and sess.task is not None and not sess.task.done()


async def _run(sess: _LoginSession) -> None:
    try:
        async with launch_persistent_context() as (_p, ctx):
            ctx.on("close", lambda *_: sess.close_event.set())
            page = await ctx.new_page()
            try:
                await page.goto("https://shopee.sg/", wait_until="domcontentloaded")
            except Exception as exc:
                log.warning("login: initial nav failed: %s", exc)
            log.info("login: shopee profile open — waiting for close signal")
            await sess.close_event.wait()
            log.info("login: close signalled — tearing down chrome")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        sess.error = str(exc)
        log.exception("login: session crashed")


async def open_session() -> dict:
    global _session
    if _is_running(_session):
        return {"status": "already_open", **status()}
    sess = _LoginSession()
    sess.opened_at = datetime.now(timezone.utc).isoformat()
    sess.task = asyncio.create_task(_run(sess))
    _session = sess
    return {"status": "opening", **status()}


async def close_session() -> dict:
    global _session
    sess = _session
    if not _is_running(sess):
        _session = None
        return {"status": "not_open"}
    assert sess is not None
    sess.close_event.set()
    try:
        await asyncio.wait_for(sess.task, timeout=15)
    except asyncio.TimeoutError:
        log.warning("login: task did not exit in 15s — cancelling")
        sess.task.cancel()
        try:
            await sess.task
        except (asyncio.CancelledError, Exception):
            pass
    err = sess.error
    _session = None
    return {"status": "closed", "error": err}


def status() -> dict:
    """Return current state. If the background task has finished
    (e.g., user closed chrome manually), reap it and report closed."""
    global _session
    sess = _session
    if sess is None:
        return {"open": False, "profile_dir": str(PROFILE_DIR)}
    if sess.task is None or sess.task.done():
        err = sess.error
        if sess.task and sess.task.done() and not err:
            exc = sess.task.exception() if not sess.task.cancelled() else None
            err = str(exc) if exc else None
        _session = None
        return {"open": False, "profile_dir": str(PROFILE_DIR), "error": err}
    return {
        "open": True,
        "profile_dir": str(PROFILE_DIR),
        "opened_at": sess.opened_at,
    }


def is_open() -> bool:
    return status()["open"]
