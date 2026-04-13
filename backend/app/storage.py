"""Per-scrape JSON file output.

Layout: data/scrapes/{platform_key}/{brand_slug}/{timestamp}.json

During a scrape we write to `{timestamp}.partial.json`. On clean finish we
rename to `{timestamp}.json`. On error/cancel/pause-left-hanging, the
`.partial.json` stays in place with a `_status` field set.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# data/ lives at backend/data/ (sibling of app/)
DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "scrapes"

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _slugify(value: str) -> str:
    return _SLUG_RE.sub("_", value).strip("_") or "unknown"


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def partial_path(platform_key: str, brand_slug: str, ts: str) -> Path:
    d = DATA_ROOT / platform_key / _slugify(brand_slug)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{ts}.partial.json"


def write_records(
    path: Path,
    records: list[BaseModel],
    *,
    meta: dict[str, Any],
    status: str,
) -> None:
    """Atomic-ish write: write to tmp then rename over target."""
    payload = {
        "_status": status,  # "ok" | "error" | "cancelled" | "login_pending" | "captcha_pending"
        "_meta": meta,
        "records": [r.model_dump(mode="json") for r in records],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    tmp.replace(path)


def finalize(partial: Path) -> Path:
    """Rename {timestamp}.partial.json → {timestamp}.json."""
    final = partial.with_name(partial.name.replace(".partial.json", ".json"))
    partial.replace(final)
    return final
