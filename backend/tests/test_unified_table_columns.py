"""Per-platform column dispatch in get_unified_table.

After the per-platform record-schema split, scrape columns must reflect
the run's platform — not the union of every platform's fields. Verifies:
  - Shopee runs return only Shopee + base columns (no `category`).
  - Official-site runs return only base + `category` (no `item_id`,
    `rating_star`, `monthly_sold_count`, etc.).
  - Runs with missing/unknown `_meta.platform` fall back to the union
    of all known record classes (preserves pre-split behaviour).
"""
from __future__ import annotations

import json

import pytest

from app.brands import BrandRepo


class FakeIdentity:
    def product_key(self, record) -> str | None:
        if isinstance(record, dict):
            return record.get("product_key") or None
        return getattr(record, "product_key", None) or None


@pytest.fixture
def repo(tmp_path):
    return BrandRepo(root=tmp_path)


def _seed_run(tmp_path, platform: str | None) -> dict:
    """Write a minimal parent-run JSON file under brand=test/source=src.
    Mirrors test_enrichments.py's fixture but parameterised on platform.
    `platform=None` writes a `_meta` without the field, exercising the
    legacy fallback in get_unified_table.
    """
    runs_dir = tmp_path / "test" / "sources" / "src" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    meta: dict = {"aggregates": {"product_count": 1}}
    if platform is not None:
        meta["platform"] = platform
    parent = {
        "_status": "ok",
        "_meta": meta,
        "records": [{"product_key": "p1", "product_name": "A", "price": 1.0}],
    }
    run_id = "20260506T100000Z"
    (runs_dir / f"{run_id}.json").write_text(json.dumps(parent))
    return {"run_id": run_id}


def _scrape_col_ids(table) -> set[str]:
    return {c.id for c in table.columns if c.source == "scrape"}


def test_shopee_run_returns_only_shopee_and_base_columns(repo, tmp_path):
    seed = _seed_run(tmp_path, "shopee")
    table = repo.get_unified_table(
        "test", "src", seed["run_id"], identity=FakeIdentity(),
    )
    ids = _scrape_col_ids(table)

    # Shopee + base fields present
    assert "product_name" in ids
    assert "price" in ids
    assert "item_id" in ids
    assert "rating_star" in ids
    assert "monthly_sold_count" in ids

    # Official-site-only field absent
    assert "category" not in ids


def test_official_site_run_returns_only_official_and_base_columns(repo, tmp_path):
    seed = _seed_run(tmp_path, "official_site")
    table = repo.get_unified_table(
        "test", "src", seed["run_id"], identity=FakeIdentity(),
    )
    ids = _scrape_col_ids(table)

    # Base + official-site fields present
    assert "product_name" in ids
    assert "price" in ids
    assert "category" in ids

    # Shopee-only fields absent
    for shopee_only in (
        "item_id",
        "rating_star",
        "monthly_sold_count",
        "category_id",
        "promotion_labels",
    ):
        assert shopee_only not in ids


def test_unknown_platform_falls_back_to_union_of_known_classes(repo, tmp_path):
    seed = _seed_run(tmp_path, None)  # _meta has no platform
    table = repo.get_unified_table(
        "test", "src", seed["run_id"], identity=FakeIdentity(),
    )
    ids = _scrape_col_ids(table)

    # Union of every known platform's fields appears (legacy behaviour).
    assert "item_id" in ids  # Shopee
    assert "category" in ids  # official-site
    assert "product_name" in ids  # base
    assert "price" in ids  # base
