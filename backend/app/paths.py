"""Single source of truth for the runtime data directory.

Backed by ``platformdirs`` so one code path covers every OS we ship on:

  * macOS:   ``~/Library/Application Support/BrandScraper``
  * Windows: ``%LOCALAPPDATA%\\BrandScraper``
  * Linux:   ``~/.local/share/BrandScraper`` (or ``$XDG_DATA_HOME``)

Override with ``BRAND_SCRAPER_DATA_DIR`` (e.g. point dev at the in-repo
``backend/data`` checkout). On first launch with the new platform path,
if the legacy in-repo ``backend/data/`` directory exists it is moved
wholesale — keeps brand history and browser profiles across upgrades
without the recipient copying files between zip extractions.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import platformdirs

log = logging.getLogger(__name__)

_APP_NAME = "BrandScraper"
_LEGACY_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _resolve() -> Path:
    override = os.environ.get("BRAND_SCRAPER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    # appauthor=False suppresses the per-vendor segment Windows would otherwise
    # inject (we want %LOCALAPPDATA%\BrandScraper, not %LOCALAPPDATA%\Anthropic\BrandScraper).
    return Path(platformdirs.user_data_dir(_APP_NAME, appauthor=False))


def _migrate_legacy(target: Path) -> None:
    if target.exists():
        return
    if not _LEGACY_DATA_DIR.exists():
        return
    if target.resolve() == _LEGACY_DATA_DIR.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    log.info("Migrating data dir: %s -> %s", _LEGACY_DATA_DIR, target)
    shutil.move(str(_LEGACY_DATA_DIR), str(target))


DATA_DIR: Path = _resolve()
_migrate_legacy(DATA_DIR)
DATA_DIR.mkdir(parents=True, exist_ok=True)

BRANDS_DIR: Path = DATA_DIR / "brands"
SETTINGS_PATH: Path = DATA_DIR / "settings.json"
# Two parent dirs preserved verbatim from the prior in-repo layout — moving
# them would invalidate existing browser profiles (cookies, _abck) and break
# the ``browser-use-user-data-dir-`` substring check in browser_use's
# BrowserProfile._copy_profile.
BROWSER_PROFILES_DIR: Path = DATA_DIR / "browser_profiles"
HIDDEN_BROWSER_PROFILES_DIR: Path = DATA_DIR / ".browser_profiles"
