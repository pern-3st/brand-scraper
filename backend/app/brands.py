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
import logging
import re
import secrets
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)


_SLUG_STRIP = re.compile(r"[^a-z0-9-]+")
_SLUG_COLLAPSE = re.compile(r"-+")

ENRICHMENT_DIR_SUFFIX = ".enrichments"


def new_enrichment_id() -> str:
    """Timestamp plus 4-hex-char random suffix. Prevents collisions when two
    enrichments are kicked off within the same second against the same run."""
    from app.storage import timestamp
    return f"{timestamp()}-{secrets.token_hex(2)}"


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
        self._backfill_source_names()

    def _backfill_source_names(self) -> None:
        """One-shot: ensure every source.json has a `name` field. Derives the
        name from the platform's primary URL (`shop_url` for Shopee,
        `brand_url` for official_site). Idempotent — sources that already
        have a `name` are left alone."""
        if not self.root.exists():
            return
        for brand_dir in self.root.iterdir():
            sources_dir = brand_dir / "sources"
            if not sources_dir.exists():
                continue
            for source_dir in sources_dir.iterdir():
                sj = source_dir / "source.json"
                if not sj.exists():
                    continue
                try:
                    data = json.loads(sj.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(data.get("name"), str) and data["name"]:
                    continue
                spec = data.get("spec") or {}
                derived = (
                    spec.get("shop_url")
                    if data.get("platform") in {"shopee", "lazada"}
                    else spec.get("brand_url")
                )
                if not isinstance(derived, str) or not derived:
                    derived = data.get("id", "unnamed")
                data["name"] = derived
                sj.write_text(json.dumps(data, indent=2))

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

    def add_source(
        self, *, brand_id: str, platform: str, name: str, spec: dict[str, Any]
    ) -> "Source":
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
            name=name,
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

    def update_source(
        self,
        brand_id: str,
        source_id: str,
        *,
        spec: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> "Source":
        existing = self.get_source(brand_id, source_id)
        if existing is None:
            raise SourceNotFound(f"source {source_id!r} not found under {brand_id!r}")
        updated = Source(
            id=existing.id,
            brand_id=existing.brand_id,
            platform=existing.platform,
            name=existing.name if name is None else name,
            spec=existing.spec if spec is None else spec,
            created_at=existing.created_at,
        )
        path = self._source_dir(brand_id, source_id) / "source.json"
        path.write_text(json.dumps(asdict(updated), indent=2))
        return updated

    def delete_source(self, brand_id: str, source_id: str) -> bool:
        import shutil
        sdir = self._source_dir(brand_id, source_id)
        if not sdir.exists():
            return False
        shutil.rmtree(sdir)
        return True

    # --- runs ---

    _AGGREGATE_KEYS = ("product_count", "price_min", "price_max", "category_count")

    def _runs_dir(self, brand_id: str, source_id: str) -> Path:
        return self._source_dir(brand_id, source_id) / "runs"

    def list_runs(self, brand_id: str, source_id: str) -> list["RunSummary"]:
        rdir = self._runs_dir(brand_id, source_id)
        if not rdir.exists():
            return []

        # Collect one entry per run_id; prefer the final (`.json`) over `.partial.json`.
        by_id: dict[str, Path] = {}
        for p in rdir.iterdir():
            name = p.name
            if name.endswith(".log.jsonl"):
                continue
            if name.endswith(".partial.json"):
                run_id = name[: -len(".partial.json")]
                by_id.setdefault(run_id, p)  # partial loses to any existing final
            elif name.endswith(".json"):
                run_id = name[: -len(".json")]
                by_id[run_id] = p  # final always wins

        out: list[RunSummary] = []
        for run_id, p in by_id.items():
            data = json.loads(p.read_text())
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
        rdir = self._runs_dir(brand_id, source_id)
        final = rdir / f"{run_id}.json"
        if final.exists():
            return json.loads(final.read_text())
        partial = rdir / f"{run_id}.partial.json"
        if partial.exists():
            return json.loads(partial.read_text())
        return None

    def delete_run(self, brand_id: str, source_id: str, run_id: str) -> bool:
        import shutil
        rdir = self._runs_dir(brand_id, source_id)
        final = rdir / f"{run_id}.json"
        partial = rdir / f"{run_id}.partial.json"
        log = rdir / f"{run_id}.log.jsonl"
        enrichments = rdir / f"{run_id}{ENRICHMENT_DIR_SUFFIX}"

        deleted = False
        if final.exists():
            final.unlink()
            deleted = True
        if partial.exists():
            partial.unlink()
            deleted = True
        if log.exists():
            log.unlink()
            # don't flip `deleted` on log-only — if only the log exists, the run "doesn't exist"
        if enrichments.exists():
            # Cascade: any enrichment pass is derived from this run; orphaning
            # them would surface as ghost passes under a new run with the same id.
            shutil.rmtree(enrichments)
        return deleted

    def partial_run_path(self, brand_id: str, source_id: str, run_id: str) -> Path:
        rdir = self._runs_dir(brand_id, source_id)
        rdir.mkdir(parents=True, exist_ok=True)
        return rdir / f"{run_id}.partial.json"

    def log_path(self, brand_id: str, source_id: str, run_id: str) -> Path:
        rdir = self._runs_dir(brand_id, source_id)
        rdir.mkdir(parents=True, exist_ok=True)
        return rdir / f"{run_id}.log.jsonl"

    def get_run_logs(self, brand_id: str, source_id: str, run_id: str) -> list[dict[str, Any]]:
        path = self._runs_dir(brand_id, source_id) / f"{run_id}.log.jsonl"
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def finalize_run(self, partial_path: Path) -> Path:
        final = partial_path.with_name(partial_path.name.replace(".partial.json", ".json"))
        partial_path.replace(final)
        return final

    # --- enrichments ---

    def _enrichments_dir(self, brand_id: str, source_id: str, run_id: str) -> Path:
        return self._runs_dir(brand_id, source_id) / f"{run_id}{ENRICHMENT_DIR_SUFFIX}"

    def partial_enrichment_path(
        self, brand_id: str, source_id: str, run_id: str, enrichment_id: str
    ) -> Path:
        edir = self._enrichments_dir(brand_id, source_id, run_id)
        edir.mkdir(parents=True, exist_ok=True)
        return edir / f"{enrichment_id}.partial.json"

    def enrichment_log_path(
        self, brand_id: str, source_id: str, run_id: str, enrichment_id: str
    ) -> Path:
        edir = self._enrichments_dir(brand_id, source_id, run_id)
        edir.mkdir(parents=True, exist_ok=True)
        return edir / f"{enrichment_id}.log.jsonl"

    def get_enrichment_logs(
        self, brand_id: str, source_id: str, run_id: str, enrichment_id: str,
    ) -> list[dict[str, Any]]:
        path = (
            self._enrichments_dir(brand_id, source_id, run_id)
            / f"{enrichment_id}.log.jsonl"
        )
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def finalize_enrichment(self, partial_path: Path) -> Path:
        final = partial_path.with_name(partial_path.name.replace(".partial.json", ".json"))
        partial_path.replace(final)
        return final

    def list_enrichments(
        self, brand_id: str, source_id: str, run_id: str
    ) -> list[dict[str, Any]]:
        edir = self._enrichments_dir(brand_id, source_id, run_id)
        if not edir.exists():
            return []
        by_id: dict[str, Path] = {}
        for p in edir.iterdir():
            name = p.name
            if name.endswith(".log.jsonl"):
                continue
            if name.endswith(".partial.json"):
                eid = name[: -len(".partial.json")]
                by_id.setdefault(eid, p)
            elif name.endswith(".json"):
                eid = name[: -len(".json")]
                by_id[eid] = p
        out: list[dict[str, Any]] = []
        for eid, path in by_id.items():
            data = json.loads(path.read_text())
            meta = data.get("_meta", {}) or {}
            out.append({
                "id": eid,
                "status": data.get("_status", "unknown"),
                "aggregates": meta.get("aggregates", {}) or {},
                "request": meta.get("request", {}) or {},
            })
        out.sort(key=lambda e: e["id"], reverse=True)
        return out

    def get_enrichment_history(
        self, brand_id: str, *, platform: str
    ) -> dict[str, Any]:
        """Aggregate prior enrichment requests for a brand on a given platform.

        Returns a dict with:
          - ``most_recent``: the request payload from the newest enrichment
            (curated_fields + freeform_prompts) so the UI can pre-fill it.
            ``None`` if there are no prior enrichments.
          - ``saved_prompts``: distinct freeform prompts across every pass for
            the brand+platform, deduped by id, with ``use_count`` and
            ``last_used_at``. Sorted newest-first by ``last_used_at``.

        The newest pass wins for a prompt's ``label`` and ``prompt`` text — if
        the user re-asks the same question with rephrased wording, the latest
        wording is what they'll see next time.

        Raises ``KeyError`` when the brand does not exist.
        """
        if self.get_brand(brand_id) is None:
            raise KeyError(f"brand {brand_id!r} not found")

        # Walk every pass (final or partial) under every source matching the
        # platform. We carry (eid, request) tuples so we can sort by eid (which
        # is timestamped).
        passes: list[tuple[str, dict[str, Any]]] = []
        for source in self.list_sources(brand_id):
            if source.platform != platform:
                continue
            sdir = self._source_dir(brand_id, source.id) / "runs"
            if not sdir.exists():
                continue
            for child in sdir.iterdir():
                if not (child.is_dir() and child.name.endswith(ENRICHMENT_DIR_SUFFIX)):
                    continue
                for p in child.iterdir():
                    name = p.name
                    if name.endswith(".log.jsonl"):
                        continue
                    if name.endswith(".partial.json"):
                        eid = name[: -len(".partial.json")]
                    elif name.endswith(".json"):
                        eid = name[: -len(".json")]
                    else:
                        continue
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    request = (data.get("_meta") or {}).get("request") or {}
                    passes.append((eid, request))

        passes.sort(key=lambda t: t[0], reverse=True)

        most_recent: dict[str, Any] | None = None
        if passes:
            req = passes[0][1]
            most_recent = {
                "curated_fields": list(req.get("curated_fields") or []),
                "freeform_prompts": list(req.get("freeform_prompts") or []),
            }

        # Dedupe freeform prompts by id; newest wording wins. Iterate newest
        # first so the first sighting of an id keeps its wording.
        prompts_by_id: dict[str, dict[str, Any]] = {}
        for eid, req in passes:
            for fp in req.get("freeform_prompts") or []:
                if not isinstance(fp, dict):
                    continue
                fid = fp.get("id")
                if not isinstance(fid, str):
                    continue
                existing = prompts_by_id.get(fid)
                if existing is None:
                    prompts_by_id[fid] = {
                        "id": fid,
                        "label": fp.get("label") or fid,
                        "prompt": fp.get("prompt") or "",
                        "last_used_at": eid,
                        "use_count": 1,
                    }
                else:
                    existing["use_count"] += 1

        saved = list(prompts_by_id.values())
        saved.sort(key=lambda p: p["last_used_at"], reverse=True)
        return {"most_recent": most_recent, "saved_prompts": saved}

    def enriched_field_map(
        self, brand_id: str, source_id: str, run_id: str
    ) -> dict[str, set[str]]:
        """Return per-product_key set of field ids that already have non-null
        values across every enrichment pass (including in-progress partial files)
        for this parent run. Used by the runner to skip already-enriched products
        on subsequent passes.

        A field counts as enriched only when its value is non-null. Rows with
        ``errors["_all"]`` or empty ``values`` contribute nothing — those are
        failures we want to retry.
        """
        edir = self._enrichments_dir(brand_id, source_id, run_id)
        if not edir.exists():
            return {}
        out: dict[str, set[str]] = {}
        for p in edir.iterdir():
            name = p.name
            if name.endswith(".log.jsonl"):
                continue
            if not (name.endswith(".json") or name.endswith(".partial.json")):
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for r in data.get("results", []) or []:
                if not isinstance(r, dict):
                    continue
                pk = r.get("product_key")
                if not isinstance(pk, str) or not pk:
                    continue
                if "_all" in (r.get("errors") or {}):
                    continue
                values = r.get("values") or {}
                if not isinstance(values, dict):
                    continue
                populated = {fid for fid, v in values.items() if v is not None}
                if not populated:
                    continue
                out.setdefault(pk, set()).update(populated)
        return out

    def get_enrichment_payload(
        self, brand_id: str, source_id: str, run_id: str, enrichment_id: str
    ) -> dict | None:
        edir = self._enrichments_dir(brand_id, source_id, run_id)
        final = edir / f"{enrichment_id}.json"
        if final.exists():
            return json.loads(final.read_text())
        partial = edir / f"{enrichment_id}.partial.json"
        if partial.exists():
            return json.loads(partial.read_text())
        return None

    def delete_enrichment(
        self, brand_id: str, source_id: str, run_id: str, enrichment_id: str
    ) -> bool:
        edir = self._enrichments_dir(brand_id, source_id, run_id)
        if not edir.exists():
            return False
        final = edir / f"{enrichment_id}.json"
        partial = edir / f"{enrichment_id}.partial.json"
        log = edir / f"{enrichment_id}.log.jsonl"
        deleted = False
        if final.exists():
            final.unlink()
            deleted = True
        if partial.exists():
            partial.unlink()
            deleted = True
        if log.exists():
            log.unlink()
        return deleted

    def get_unified_table(
        self,
        brand_id: str,
        source_id: str,
        run_id: str,
        *,
        identity: Any,  # ProductIdentity-like; typed Any to avoid importing platforms.base here
        include: "str | list[str]" = "latest_per_field",
    ) -> "UnifiedTable":
        """Build the unified scrape + enrichment table for a run.

        - Scrape columns come from the run's platform-specific record class
          (resolved via ``RECORD_CLASSES[_meta.platform]``).
        - Enrichment columns come from the selected passes.
        - Rows are keyed by ``identity.product_key(record)``; records whose
          key is ``None`` are skipped (logged in ``products_skipped_no_key``
          at write time; silently dropped at read time).
        - Collisions on column id: ``latest_per_field`` (default) keeps the
          most recent pass per id. ``all`` exposes both, labelled per pass.
        """
        from app.models import RECORD_CLASSES, UnifiedColumn, UnifiedTable

        parent = self.get_run_payload(brand_id, source_id, run_id)
        if parent is None:
            raise KeyError(f"run {run_id!r} not found under {brand_id}/{source_id}")

        scrape_records = parent.get("records", []) or []
        rows_by_key: dict[str, dict[str, Any]] = {}
        for raw in scrape_records:
            if not isinstance(raw, dict):
                continue
            pk = identity.product_key(raw)
            if pk is None:
                continue
            row = {"product_key": pk, **raw}
            rows_by_key[pk] = row

        # Scrape column descriptors in schema order, dispatched on platform.
        platform = (parent.get("_meta") or {}).get("platform")
        record_cls = RECORD_CLASSES.get(platform) if isinstance(platform, str) else None
        if record_cls is None:
            log.warning(
                "get_unified_table: run %s/%s/%s has unknown platform %r — "
                "falling back to union of all known record classes",
                brand_id, source_id, run_id, platform,
            )
            scrape_columns = _build_scrape_columns_union(RECORD_CLASSES.values())
        else:
            scrape_columns = _build_scrape_columns(record_cls)

        # Resolve included enrichment passes (newest first from list_enrichments).
        passes = self.list_enrichments(brand_id, source_id, run_id)
        passes = [p for p in passes if p["status"] != "in_progress"]
        # Explicit id list filters to the named passes, then falls back to
        # latest-per-field disambiguation (newest pass wins on collision).
        mode: str
        if isinstance(include, list):
            allowed = set(include)
            selected = [p for p in passes if p["id"] in allowed]
            mode = "latest_per_field"
        elif include == "all":
            selected = passes
            mode = "all"
        elif include == "latest_per_field":
            selected = passes
            mode = "latest_per_field"
        else:
            raise ValueError(f"invalid include value {include!r}")

        enrichment_columns: list[UnifiedColumn] = []
        # When latest_per_field, we need most-recent wins: iterate newest→oldest,
        # write if not present. list_enrichments returns newest first.
        seen_field_ids: set[str] = set()
        for pass_summary in selected:
            eid = pass_summary["id"]
            payload = self.get_enrichment_payload(brand_id, source_id, run_id, eid)
            if payload is None:
                continue
            results = payload.get("results", []) or []
            field_type_map = _build_field_type_map(payload.get("_meta", {}))
            # Collect fields used in this pass (from values across results).
            pass_field_ids: list[str] = []
            for r in results:
                values = r.get("values", {}) or {}
                for fid in values.keys():
                    if fid not in pass_field_ids:
                        pass_field_ids.append(fid)

            # Materialise column descriptors and merge values into rows.
            for fid in pass_field_ids:
                if mode == "latest_per_field":
                    if fid in seen_field_ids:
                        continue
                    seen_field_ids.add(fid)
                    enrichment_columns.append(UnifiedColumn(
                        id=fid, label=fid, type=field_type_map.get(fid),
                        source="enrichment", enrichment_id=eid,
                    ))
                else:  # "all" or explicit list
                    # Disambiguate id per pass so the frontend can map column → cell
                    # without needing to cross-reference enrichment_id.
                    enrichment_columns.append(UnifiedColumn(
                        id=f"{fid}::{eid}", label=f"{fid} ({eid})",
                        type=field_type_map.get(fid),
                        source="enrichment", enrichment_id=eid,
                    ))

            for r in results:
                pk = r.get("product_key")
                if pk not in rows_by_key:
                    continue
                values = r.get("values", {}) or {}
                for fid, val in values.items():
                    if mode == "latest_per_field":
                        # Newest pass wins: we iterate newest→oldest, so
                        # `setdefault` preserves the first (newest) write.
                        rows_by_key[pk].setdefault(fid, val)
                    else:
                        # "all" mode namespaces per pass so multiple columns
                        # for the same field can coexist.
                        rows_by_key[pk][f"{fid}::{eid}"] = val

        return UnifiedTable(
            columns=scrape_columns + enrichment_columns,
            rows=list(rows_by_key.values()),
        )


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
    name: str
    spec: dict[str, Any]
    created_at: str


def _new_source_id() -> str:
    return secrets.token_hex(4)  # 8 hex chars — short, collision-resistant at small N


_SCRAPE_TYPE_MAP: dict[type, str] = {
    str: "str",
    int: "int",
    float: "float",
    bool: "bool",
}


def _build_scrape_columns(record_cls: type) -> list[Any]:
    """Introspect ``record_cls.model_fields`` to build UnifiedColumn descriptors.

    Unknown types (e.g. ``datetime``) surface with ``type=None`` — the frontend
    falls back to a generic string renderer.
    """
    from app.models import UnifiedColumn
    cols: list[UnifiedColumn] = []
    for field_name, info in record_cls.model_fields.items():
        # Strip Optional[] to read the base type.
        ann = info.annotation
        base = _unwrap_optional(ann)
        mapped: str | None = None
        if base in _SCRAPE_TYPE_MAP:
            mapped = _SCRAPE_TYPE_MAP[base]
        elif _is_list_of_str(base):
            mapped = "list[str]"
        cols.append(UnifiedColumn(
            id=field_name, label=field_name, type=mapped, source="scrape",
        ))
    return cols


def _build_scrape_columns_union(record_classes: Iterable[type]) -> list[Any]:
    """Legacy fallback for runs without a recognisable ``_meta.platform``:
    union the columns of every known record class, deduping by id while
    preserving first-seen order. Equivalent to the pre-split single-model
    behaviour, so old test fixtures without ``_meta.platform`` still work.
    """
    from app.models import UnifiedColumn
    seen: dict[str, UnifiedColumn] = {}
    for cls in record_classes:
        for col in _build_scrape_columns(cls):
            if col.id not in seen:
                seen[col.id] = col
    return list(seen.values())


def _unwrap_optional(ann: Any) -> Any:
    import typing as _t
    origin = _t.get_origin(ann)
    if origin is _t.Union or str(origin) == "typing.Union" or (
        hasattr(_t, "UnionType") and origin is getattr(_t, "UnionType", None)
    ):
        args = [a for a in _t.get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    # Handle PEP 604 `X | None` which comes through differently.
    import types
    if isinstance(ann, types.UnionType):
        args = [a for a in ann.__args__ if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _is_list_of_str(tp: Any) -> bool:
    import typing as _t
    if _t.get_origin(tp) is list:
        args = _t.get_args(tp)
        return bool(args) and args[0] is str
    return False


def _build_field_type_map(meta: dict[str, Any]) -> dict[str, str]:
    """Read the types of curated fields declared in the pass's request.
    Freeform prompts are all ``str | None`` by construction, so their type is
    reported as ``str``.
    """
    out: dict[str, str] = {}
    req = meta.get("request", {}) or {}
    # Curated fields store only ids in the request; without the platform catalog
    # we don't know their types. Leave them unmapped — frontend falls back to
    # a generic renderer.
    for prompt in req.get("freeform_prompts", []) or []:
        fid = prompt.get("id")
        if isinstance(fid, str):
            out[fid] = "str"
    return out


def compute_run_aggregates(*, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Platform-agnostic aggregate computation, stored in run `_meta["aggregates"]`.

    All platform record classes share `ProductRecordBase`, so one formula
    works everywhere:
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
