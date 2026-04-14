"""Local runtime settings (OpenRouter key/model).

Stored as a plaintext JSON file in `backend/data/settings.json` so the user
can edit via the UI without touching the repo. Falls back to env vars when
the file is absent or a field is empty — preserves the old `.env` flow.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "settings.json"

DEFAULT_MODEL = "x-ai/grok-4.1-fast"


def _read_file() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def load() -> dict[str, str]:
    """Return the effective settings (file → env → default)."""
    data = _read_file()
    api_key = (data.get("openrouter_api_key") or "").strip() or os.getenv("OPENROUTER_API_KEY", "")
    model = (data.get("openrouter_model") or "").strip() or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    return {"openrouter_api_key": api_key, "openrouter_model": model}


def save(*, openrouter_api_key: str | None, openrouter_model: str | None) -> None:
    current = _read_file()
    if openrouter_api_key is not None:
        current["openrouter_api_key"] = openrouter_api_key
    if openrouter_model is not None:
        current["openrouter_model"] = openrouter_model
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2))
    tmp.replace(SETTINGS_PATH)


def masked_view() -> dict[str, Any]:
    """Public representation — never returns the full key."""
    eff = load()
    key = eff["openrouter_api_key"]
    return {
        "openrouter_api_key_set": bool(key),
        "openrouter_api_key_hint": (key[:6] + "…" + key[-4:]) if len(key) >= 12 else ("…" + key[-4:] if key else ""),
        "openrouter_model": eff["openrouter_model"],
    }
