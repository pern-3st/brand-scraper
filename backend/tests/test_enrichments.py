"""Tests for Phase 1 enrichment storage: path helpers, list/delete,
get_unified_table join logic."""
from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from app.brands import BrandRepo, ENRICHMENT_DIR_SUFFIX


class FakeIdentity:
    """Test stub for ProductIdentity; keys off `product_key` in the record dict."""
    def product_key(self, record) -> str | None:
        if isinstance(record, dict):
            pk = record.get("product_key")
        else:
            pk = getattr(record, "product_key", None)
        return pk if pk else None


@pytest.fixture
def repo(tmp_path):
    return BrandRepo(root=tmp_path)


@pytest.fixture
def seeded(repo, tmp_path):
    """Brand + source + one parent run with three records."""
    repo.create_brand(name="Nike")
    source = repo.add_source(
        brand_id="nike",
        platform="official_site",
        spec={"brand_url": "https://nike.com", "section": "mens", "categories": ["x"], "max_products": 1},
    )
    runs_dir = tmp_path / "nike" / "sources" / source.id / "runs"
    parent = {
        "_status": "ok",
        "_meta": {"platform": "official_site", "aggregates": {"product_count": 3}},
        "records": [
            {"product_key": "p1", "product_name": "A", "price": 10.0},
            {"product_key": "p2", "product_name": "B", "price": 20.0},
            {"product_key": None, "product_name": "C", "price": 30.0},  # will be skipped
        ],
    }
    run_id = "20260424T100000Z"
    (runs_dir / f"{run_id}.json").write_text(json.dumps(parent))
    return {
        "source_id": source.id,
        "run_id": run_id,
        "runs_dir": runs_dir,
    }


def _write_enrichment(runs_dir, run_id, enr_id, *, status="ok", results=None, meta_extra=None):
    edir = runs_dir / f"{run_id}{ENRICHMENT_DIR_SUFFIX}"
    edir.mkdir(exist_ok=True)
    meta = {"parent_run_id": run_id, "started_at": enr_id}
    if meta_extra:
        meta.update(meta_extra)
    payload = {"_status": status, "_meta": meta, "results": results or []}
    suffix = ".partial.json" if status == "in_progress" else ".json"
    (edir / f"{enr_id}{suffix}").write_text(json.dumps(payload))


# --- path helpers -----------------------------------------------------------


def test_partial_enrichment_path_creates_directory(repo, seeded):
    path = repo.partial_enrichment_path(
        "nike", seeded["source_id"], seeded["run_id"], "20260424T120000Z-a3f1"
    )
    assert path.name == "20260424T120000Z-a3f1.partial.json"
    assert path.parent.name == f"{seeded['run_id']}{ENRICHMENT_DIR_SUFFIX}"
    assert path.parent.exists()


def test_finalize_enrichment_renames_partial_to_final(repo, seeded):
    partial = repo.partial_enrichment_path(
        "nike", seeded["source_id"], seeded["run_id"], "xyz"
    )
    partial.write_text("{}")
    final = repo.finalize_enrichment(partial)
    assert final.name == "xyz.json"
    assert final.exists()
    assert not partial.exists()


def test_list_enrichments_returns_summaries(repo, seeded):
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "20260424T120000Z-a3f1",
                      meta_extra={"aggregates": {"products_enriched": 2}})
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "20260424T130000Z-b7c2",
                      status="cancelled")
    summaries = repo.list_enrichments("nike", seeded["source_id"], seeded["run_id"])
    # Newest first
    assert [s["id"] for s in summaries] == ["20260424T130000Z-b7c2", "20260424T120000Z-a3f1"]
    assert summaries[1]["status"] == "ok"
    assert summaries[0]["status"] == "cancelled"


def test_list_enrichments_no_directory_returns_empty(repo, seeded):
    assert repo.list_enrichments("nike", seeded["source_id"], seeded["run_id"]) == []


def test_list_enrichments_prefers_final_over_partial(repo, seeded):
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "dup", status="in_progress")
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "dup", status="ok")
    summaries = repo.list_enrichments("nike", seeded["source_id"], seeded["run_id"])
    assert len(summaries) == 1
    assert summaries[0]["status"] == "ok"


def test_delete_enrichment_removes_all_variants(repo, seeded):
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "gone")
    edir = seeded["runs_dir"] / f"{seeded['run_id']}{ENRICHMENT_DIR_SUFFIX}"
    (edir / "gone.log.jsonl").write_text("{}\n")
    assert repo.delete_enrichment("nike", seeded["source_id"], seeded["run_id"], "gone") is True
    assert not (edir / "gone.json").exists()
    assert not (edir / "gone.log.jsonl").exists()


def test_delete_enrichment_missing_returns_false(repo, seeded):
    assert repo.delete_enrichment("nike", seeded["source_id"], seeded["run_id"], "nope") is False


# --- enrichment ID uniqueness ----------------------------------------------


def test_new_enrichment_id_format():
    from app.brands import new_enrichment_id
    eid = new_enrichment_id()
    ts, rand = eid.rsplit("-", 1)
    assert len(rand) == 4
    assert all(c in "0123456789abcdef" for c in rand)
    # Timestamp portion: YYYYMMDDTHHMMSSZ (16 chars ending with Z)
    assert len(ts) == 16
    assert ts.endswith("Z")


def test_new_enrichment_id_does_not_collide_within_same_second():
    from app.brands import new_enrichment_id
    ids = {new_enrichment_id() for _ in range(100)}
    # With 4 hex chars and 100 draws, birthday probability of collision ~ 0.076.
    # Flakiness is acceptable for a sanity test — we're mainly proving the random
    # suffix actually varies. Assert at least 95 unique (allows a couple of collisions).
    assert len(ids) >= 95


# --- get_unified_table ------------------------------------------------------


def test_unified_table_scrape_only(repo, seeded):
    table = repo.get_unified_table(
        "nike", seeded["source_id"], seeded["run_id"],
        identity=FakeIdentity(),
    )
    # Two rows (third parent record has no product_key → skipped)
    assert len(table.rows) == 2
    keys = {row["product_key"] for row in table.rows}
    assert keys == {"p1", "p2"}
    # Scrape columns include the _Rec fields
    col_ids = [c.id for c in table.columns]
    assert "product_name" in col_ids
    assert "price" in col_ids
    # All columns from scrape have source == "scrape"
    assert all(c.source == "scrape" for c in table.columns)


def test_unified_table_with_one_enrichment_pass(repo, seeded):
    _write_enrichment(
        seeded["runs_dir"], seeded["run_id"], "20260424T120000Z-a3f1",
        results=[
            {"product_key": "p1", "values": {"description": "Soft tee", "is_vegan": True}, "errors": {}, "enriched_at": "2026-04-24T12:01:00Z"},
            {"product_key": "p2", "values": {"description": "Cotton hoodie", "is_vegan": True}, "errors": {}, "enriched_at": "2026-04-24T12:02:00Z"},
        ],
        meta_extra={"request": {"curated_fields": ["description"], "freeform_prompts": [{"id": "is_vegan", "label": "Is vegan?", "prompt": "..."}]}},
    )
    table = repo.get_unified_table(
        "nike", seeded["source_id"], seeded["run_id"],
        identity=FakeIdentity(),
    )
    col_ids = [c.id for c in table.columns]
    assert "description" in col_ids
    assert "is_vegan" in col_ids
    row_by_key = {r["product_key"]: r for r in table.rows}
    assert row_by_key["p1"]["description"] == "Soft tee"
    assert row_by_key["p1"]["is_vegan"] is True


def test_unified_table_latest_per_field_resolves_collision(repo, seeded):
    # Older pass sets description="old"; newer pass sets description="new".
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "20260424T120000Z-aaaa",
        results=[{"product_key": "p1", "values": {"description": "old"}, "errors": {}, "enriched_at": "2026-04-24T12:00:00Z"}])
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "20260424T130000Z-bbbb",
        results=[{"product_key": "p1", "values": {"description": "new"}, "errors": {}, "enriched_at": "2026-04-24T13:00:00Z"}])
    table = repo.get_unified_table(
        "nike", seeded["source_id"], seeded["run_id"],
        identity=FakeIdentity(),
        include="latest_per_field",
    )
    row = next(r for r in table.rows if r["product_key"] == "p1")
    assert row["description"] == "new"
    # Only one description column surfaces under latest_per_field
    desc_cols = [c for c in table.columns if c.id == "description"]
    assert len(desc_cols) == 1


def test_unified_table_all_keeps_both_passes(repo, seeded):
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "20260424T120000Z-aaaa",
        results=[{"product_key": "p1", "values": {"description": "old"}, "errors": {}, "enriched_at": "2026-04-24T12:00:00Z"}])
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "20260424T130000Z-bbbb",
        results=[{"product_key": "p1", "values": {"description": "new"}, "errors": {}, "enriched_at": "2026-04-24T13:00:00Z"}])
    table = repo.get_unified_table(
        "nike", seeded["source_id"], seeded["run_id"],
        identity=FakeIdentity(),
        include="all",
    )
    # Both passes surface their own column
    desc_cols = [c for c in table.columns if c.label.startswith("description") or c.id.startswith("description")]
    assert len(desc_cols) == 2
    # Each column carries its enrichment_id
    eids = {c.enrichment_id for c in desc_cols}
    assert eids == {"20260424T120000Z-aaaa", "20260424T130000Z-bbbb"}


def test_unified_table_explicit_id_list(repo, seeded):
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "keep",
        results=[{"product_key": "p1", "values": {"x": 1}, "errors": {}, "enriched_at": "2026-04-24T12:00:00Z"}])
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "skip",
        results=[{"product_key": "p1", "values": {"y": 2}, "errors": {}, "enriched_at": "2026-04-24T12:00:00Z"}])
    table = repo.get_unified_table(
        "nike", seeded["source_id"], seeded["run_id"],
        identity=FakeIdentity(),
        include=["keep"],
    )
    col_ids = {c.id for c in table.columns}
    assert "x" in col_ids
    assert "y" not in col_ids


def test_unified_table_skips_none_keys(repo, seeded):
    # Parent has 3 records; one has product_key=None and must be skipped.
    table = repo.get_unified_table(
        "nike", seeded["source_id"], seeded["run_id"],
        identity=FakeIdentity(),
    )
    assert len(table.rows) == 2  # third record skipped


def test_unified_table_skips_partial_passes_by_default(repo, seeded):
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "done",
        results=[{"product_key": "p1", "values": {"a": 1}, "errors": {}, "enriched_at": "2026-04-24T12:00:00Z"}])
    _write_enrichment(seeded["runs_dir"], seeded["run_id"], "running", status="in_progress",
        results=[{"product_key": "p1", "values": {"b": 2}, "errors": {}, "enriched_at": "2026-04-24T12:00:00Z"}])
    table = repo.get_unified_table(
        "nike", seeded["source_id"], seeded["run_id"],
        identity=FakeIdentity(),
        include="all",
    )
    col_ids = {c.id for c in table.columns}
    # `a` surfaces under the namespaced "all" id; `b` never appears because its
    # partial pass is excluded.
    assert "a::done" in col_ids
    assert not any(c.id.startswith("b") for c in table.columns if c.source == "enrichment")


def test_unified_table_missing_run_raises(repo, seeded):
    with pytest.raises(KeyError):
        repo.get_unified_table(
            "nike", seeded["source_id"], "does-not-exist",
            identity=FakeIdentity(),
        )
