"""Migrate legacy backend/data/scrapes/<platform>/<brand>/<ts>.json
into backend/data/brands/<brand>/sources/<id>/runs/<ts>.json.

Idempotent: skips brands that already exist in the new layout.
Run with: uv run python scripts/migrate_to_brands.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / "data" / "scrapes"
NEW = ROOT / "data" / "brands"

sys.path.insert(0, str(ROOT))
from app.brands import BrandRepo, compute_run_aggregates, slugify_brand_name  # noqa: E402


def main() -> None:
    if not OLD.exists():
        print("No legacy data found; nothing to migrate.")
        return
    repo = BrandRepo(root=NEW)
    for platform_dir in sorted(OLD.iterdir()):
        if not platform_dir.is_dir():
            continue
        platform = platform_dir.name
        for brand_dir in sorted(platform_dir.iterdir()):
            if not brand_dir.is_dir():
                continue
            legacy_slug = brand_dir.name
            # The legacy slugifier preserved dots ("www.next.co.uk"); the new
            # slugifier strips them. Compute the new brand_id and use it
            # consistently.
            new_brand_id = slugify_brand_name(legacy_slug)
            # Create brand if absent.
            if repo.get_brand(new_brand_id) is None:
                repo.create_brand(name=legacy_slug)
                print(f"created brand {new_brand_id} (from legacy '{legacy_slug}')")
            # Build a spec from the first run's _meta.request if available.
            runs = sorted(brand_dir.glob("*.json"))
            if not runs:
                continue
            first = json.loads(runs[0].read_text())
            spec = (first.get("_meta") or {}).get("request") or {}
            spec_wo_platform = {k: v for k, v in spec.items() if k != "platform"}
            # Reuse existing source for this brand+platform if any.
            existing = [s for s in repo.list_sources(new_brand_id) if s.platform == platform]
            if existing:
                source = existing[0]
            else:
                source = repo.add_source(brand_id=new_brand_id, platform=platform, spec=spec_wo_platform)
                print(f"  + source {source.id} ({platform}) for {new_brand_id}")
            # Copy each run file, enriching _meta with nested aggregates.
            for run_path in runs:
                target = repo._runs_dir(new_brand_id, source.id) / run_path.name
                if target.exists():
                    continue
                data = json.loads(run_path.read_text())
                records = data.get("records", [])
                meta = data.get("_meta", {}) or {}
                meta["aggregates"] = compute_run_aggregates(platform=platform, records=records)
                data["_meta"] = meta
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                print(f"    migrated run {run_path.name}")
    print("done.")


if __name__ == "__main__":
    main()
