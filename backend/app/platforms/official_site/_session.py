"""Patchright persistent-context launcher for official-site enrichment.

Mirrors ``shopee/_session.py``: one persistent profile per platform so the
``_abck`` (Akamai bot-manager) and other reputation cookies age across runs.
The profile is local — Chrome locks the directory, so concurrent enrichment
runs against the official-site path will fail loudly on launch. That's
acceptable for a single-user desktop app.

Browser_use's playwright client (used by the grid scraper) uses a SEPARATE
profile dir, intentionally — they ship different Chromium binaries and we
don't want the playwright-vs-patchright driver swap to invalidate aged
cookies.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from patchright.async_api import async_playwright

log = logging.getLogger(__name__)

# Resolve to backend/. File layout:
#   backend/app/platforms/official_site/_session.py
#   parents[0] = official_site/  parents[1] = platforms/
#   parents[2] = app/            parents[3] = backend/
BACKEND_ROOT = Path(__file__).resolve().parents[3]


def profile_dir() -> Path:
    return BACKEND_ROOT / "data" / ".browser_profiles" / "official_site_patchright"


def ensure_profile_dir() -> Path:
    p = profile_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


@asynccontextmanager
async def launch_persistent_context():
    """Open the patchright persistent Chrome profile, yield ``(playwright, ctx)``.
    Cleans up the context on exit."""
    udir = ensure_profile_dir()
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(udir),
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 900},
        )
        try:
            yield p, ctx
        finally:
            await ctx.close()
