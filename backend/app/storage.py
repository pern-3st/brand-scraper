"""Per-scrape JSON file output.

Run files live under backend/data/brands/<brand>/sources/<source>/runs/ —
path construction is owned by `app.brands.BrandRepo`. This module is now
just the low-level write helpers used by the runner.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_records(
    path: Path,
    records: list[BaseModel],
    *,
    meta: dict[str, Any],
    status: str,
) -> None:
    """Atomic-ish write: write to tmp then rename over target."""
    payload = {
        "_status": status,  # "ok" | "error" | "cancelled" | "in_progress"
        "_meta": meta,
        "records": [r.model_dump(mode="json") for r in records],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    tmp.replace(path)
