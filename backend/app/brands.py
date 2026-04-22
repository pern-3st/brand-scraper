"""Brand / Source / Run persistence.

Layout:
    backend/data/brands/<brand_id>/
        brand.json                    # {id, name, created_at}
        sources/<source_id>/
            source.json               # {id, brand_id, platform, spec, created_at}
            runs/
                <run_id>.json         # finalized run
                <run_id>.partial.json # in-flight
"""
from __future__ import annotations

import json
import re
import secrets
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SLUG_STRIP = re.compile(r"[^a-z0-9-]+")
_SLUG_COLLAPSE = re.compile(r"-+")


def slugify_brand_name(name: str) -> str:
    # NFKD first, then replace any non-alphanumeric unicode char (em-dash,
    # ampersand, etc.) with a space *before* the ASCII pass, so separators
    # survive the ascii("ignore") drop.
    normalized = unicodedata.normalize("NFKD", name)
    normalized = re.sub(r"[^\w\s-]", " ", normalized, flags=re.UNICODE)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.strip().lower()
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = _SLUG_STRIP.sub("-", normalized)
    normalized = _SLUG_COLLAPSE.sub("-", normalized).strip("-")
    if not normalized:
        raise ValueError(f"Brand name {name!r} produces an empty slug")
    return normalized


class BrandAlreadyExists(Exception):
    pass


@dataclass(frozen=True)
class Brand:
    id: str
    name: str
    created_at: str  # ISO8601 UTC


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class BrandRepo:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _brand_dir(self, brand_id: str) -> Path:
        return self.root / brand_id

    def create_brand(self, *, name: str) -> Brand:
        brand_id = slugify_brand_name(name)
        brand_dir = self._brand_dir(brand_id)
        if brand_dir.exists():
            raise BrandAlreadyExists(f"brand {brand_id!r} already exists")
        brand_dir.mkdir(parents=True)
        (brand_dir / "sources").mkdir()
        brand = Brand(id=brand_id, name=name, created_at=_now_iso())
        (brand_dir / "brand.json").write_text(json.dumps(asdict(brand), indent=2))
        return brand

    def get_brand(self, brand_id: str) -> Brand | None:
        path = self._brand_dir(brand_id) / "brand.json"
        if not path.exists():
            return None
        return Brand(**json.loads(path.read_text()))

    def delete_brand(self, brand_id: str) -> bool:
        import shutil
        brand_dir = self._brand_dir(brand_id)
        if not brand_dir.exists():
            return False
        shutil.rmtree(brand_dir)
        return True

    def list_brands(self) -> list[Brand]:
        if not self.root.exists():
            return []
        brands = []
        for brand_dir in sorted(self.root.iterdir()):
            bj = brand_dir / "brand.json"
            if bj.exists():
                brands.append(Brand(**json.loads(bj.read_text())))
        return brands

    # --- sources ---

    def _sources_dir(self, brand_id: str) -> Path:
        return self._brand_dir(brand_id) / "sources"

    def _source_dir(self, brand_id: str, source_id: str) -> Path:
        return self._sources_dir(brand_id) / source_id

    def add_source(self, *, brand_id: str, platform: str, spec: dict[str, Any]) -> "Source":
        if self.get_brand(brand_id) is None:
            raise KeyError(f"brand {brand_id!r} not found")
        source_id = _new_source_id()
        sdir = self._source_dir(brand_id, source_id)
        sdir.mkdir(parents=True)
        (sdir / "runs").mkdir()
        source = Source(
            id=source_id,
            brand_id=brand_id,
            platform=platform,
            spec=spec,
            created_at=_now_iso(),
        )
        (sdir / "source.json").write_text(json.dumps(asdict(source), indent=2))
        return source

    def get_source(self, brand_id: str, source_id: str) -> "Source | None":
        path = self._source_dir(brand_id, source_id) / "source.json"
        if not path.exists():
            return None
        return Source(**json.loads(path.read_text()))

    def list_sources(self, brand_id: str) -> list["Source"]:
        sdir = self._sources_dir(brand_id)
        if not sdir.exists():
            return []
        out = []
        for child in sorted(sdir.iterdir()):
            sj = child / "source.json"
            if sj.exists():
                out.append(Source(**json.loads(sj.read_text())))
        return out

    def update_source_spec(self, brand_id: str, source_id: str, *, spec: dict[str, Any]) -> "Source":
        existing = self.get_source(brand_id, source_id)
        if existing is None:
            raise SourceNotFound(f"source {source_id!r} not found under {brand_id!r}")
        updated = Source(
            id=existing.id,
            brand_id=existing.brand_id,
            platform=existing.platform,
            spec=spec,
            created_at=existing.created_at,
        )
        path = self._source_dir(brand_id, source_id) / "source.json"
        path.write_text(json.dumps(asdict(updated), indent=2))
        return updated

    # --- runs ---

    _AGGREGATE_KEYS = ("product_count", "price_min", "price_max", "category_count")

    def _runs_dir(self, brand_id: str, source_id: str) -> Path:
        return self._source_dir(brand_id, source_id) / "runs"

    def list_runs(self, brand_id: str, source_id: str) -> list["RunSummary"]:
        rdir = self._runs_dir(brand_id, source_id)
        if not rdir.exists():
            return []
        out: list[RunSummary] = []
        for p in rdir.iterdir():
            if p.name.endswith(".partial.json"):
                continue
            if not p.name.endswith(".json"):
                continue
            data = json.loads(p.read_text())
            run_id = p.stem  # strips .json
            meta = data.get("_meta", {}) or {}
            agg = meta.get("aggregates", {}) or {}
            out.append(RunSummary(
                id=run_id,
                status=data.get("_status", "unknown"),
                aggregates={k: agg.get(k) for k in self._AGGREGATE_KEYS},
                created_at=run_id,
            ))
        out.sort(key=lambda r: r.id, reverse=True)
        return out

    def get_run_payload(self, brand_id: str, source_id: str, run_id: str) -> dict | None:
        path = self._runs_dir(brand_id, source_id) / f"{run_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def delete_run(self, brand_id: str, source_id: str, run_id: str) -> bool:
        path = self._runs_dir(brand_id, source_id) / f"{run_id}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    def partial_run_path(self, brand_id: str, source_id: str, run_id: str) -> Path:
        rdir = self._runs_dir(brand_id, source_id)
        rdir.mkdir(parents=True, exist_ok=True)
        return rdir / f"{run_id}.partial.json"

    def finalize_run(self, partial_path: Path) -> Path:
        final = partial_path.with_name(partial_path.name.replace(".partial.json", ".json"))
        partial_path.replace(final)
        return final


@dataclass(frozen=True)
class RunSummary:
    id: str         # timestamp, e.g. "20260413T020000Z"
    status: str
    aggregates: dict[str, Any]  # only the 4 aggregate fields; see _AGGREGATE_KEYS
    created_at: str  # same as id; non-ISO compact form — frontend parses


class SourceNotFound(Exception):
    pass


@dataclass(frozen=True)
class Source:
    id: str
    brand_id: str
    platform: str
    spec: dict[str, Any]
    created_at: str


def _new_source_id() -> str:
    return secrets.token_hex(4)  # 8 hex chars — short, collision-resistant at small N


def compute_run_aggregates(*, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Platform-agnostic aggregate computation, stored in run `_meta["aggregates"]`.

    Both platforms emit `ProductRecord`s, so one formula works everywhere:
      - product_count: total records in the run
      - price_min / price_max: min/max over non-null prices
      - category_count: number of distinct non-null `category` values.
        Naturally 0 for Shopee (records don't carry a category) and
        non-zero for official_site.
    """
    prices = [float(r["price"]) for r in records if r.get("price") is not None]
    categories = {r["category"] for r in records if r.get("category")}
    return {
        "product_count": len(records),
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "category_count": len(categories),
    }
