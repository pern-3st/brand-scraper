"""Tests for the brand-level enrichment history endpoint that drives
EnrichmentPanel's "remember what I picked last time" behaviour."""
from __future__ import annotations

import json

from app.brands import ENRICHMENT_DIR_SUFFIX


def _seed_brand_with_run(client, tmp_repo, *, name, platform, spec_extras=None):
    brand = client.post("/api/brands", json={"name": name}).json()
    spec = {
        "brand_url": "https://example.test",
        "section": "mens",
        "categories": ["x"],
        "max_products": 1,
    } if platform == "official_site" else {
        "shop_url": "https://shopee.sg/x", "max_products": 1,
    }
    if spec_extras:
        spec.update(spec_extras)
    src = client.post(
        f"/api/brands/{brand['id']}/sources",
        json={"platform": platform, "name": f"{platform} src", "spec": spec},
    ).json()
    run_id = "20260424T100000Z"
    runs_dir = tmp_repo._runs_dir(brand["id"], src["id"])
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(json.dumps({
        "_status": "ok",
        "_meta": {"platform": platform},
        "records": [],
    }))
    return brand["id"], src["id"], run_id, runs_dir


def _write_enrichment(
    runs_dir, run_id, enr_id, *,
    platform="official_site",
    curated=("description",),
    freeform=(),
    status="ok",
):
    edir = runs_dir / f"{run_id}{ENRICHMENT_DIR_SUFFIX}"
    edir.mkdir(exist_ok=True)
    payload = {
        "_status": status,
        "_meta": {
            "parent_run_id": run_id,
            "started_at": enr_id,
            "platform": platform,
            "request": {
                "curated_fields": list(curated),
                "freeform_prompts": list(freeform),
            },
            "aggregates": {},
        },
        "results": [],
    }
    suffix = ".partial.json" if status == "in_progress" else ".json"
    (edir / f"{enr_id}{suffix}").write_text(json.dumps(payload))


def test_history_empty_for_brand_with_no_enrichments(client, tmp_repo):
    brand_id, _, _, _ = _seed_brand_with_run(client, tmp_repo, name="Empty", platform="official_site")
    r = client.get(f"/api/brands/{brand_id}/enrichment_history?platform=official_site")
    assert r.status_code == 200
    body = r.json()
    assert body == {"most_recent": None, "saved_prompts": []}


def test_history_returns_most_recent_for_platform(client, tmp_repo):
    brand_id, _, run_id, runs_dir = _seed_brand_with_run(
        client, tmp_repo, name="Solo", platform="official_site",
    )
    _write_enrichment(
        runs_dir, run_id, "20260424T120000Z-aaaa",
        curated=["description"],
        freeform=[{"id": "is_vegan", "label": "Is vegan?", "prompt": "Is this vegan?"}],
    )
    _write_enrichment(
        runs_dir, run_id, "20260424T130000Z-bbbb",  # newer
        curated=["description", "ingredients"],
        freeform=[{"id": "is_vegan", "label": "Is vegan?", "prompt": "Updated prompt v2"}],
    )
    r = client.get(f"/api/brands/{brand_id}/enrichment_history?platform=official_site")
    assert r.status_code == 200
    body = r.json()
    assert body["most_recent"]["curated_fields"] == ["description", "ingredients"]
    assert body["most_recent"]["freeform_prompts"] == [
        {"id": "is_vegan", "label": "Is vegan?", "prompt": "Updated prompt v2"},
    ]


def test_history_dedupes_freeform_prompts_with_use_count(client, tmp_repo):
    brand_id, _, run_id, runs_dir = _seed_brand_with_run(
        client, tmp_repo, name="Multi", platform="official_site",
    )
    _write_enrichment(
        runs_dir, run_id, "20260424T120000Z-aaaa",
        freeform=[
            {"id": "is_vegan", "label": "Is vegan?", "prompt": "Is this vegan?"},
            {"id": "is_organic", "label": "Is organic?", "prompt": "Is this organic?"},
        ],
    )
    _write_enrichment(
        runs_dir, run_id, "20260424T130000Z-bbbb",
        freeform=[
            {"id": "is_vegan", "label": "Is vegan?", "prompt": "Newer wording"},
        ],
    )

    body = client.get(
        f"/api/brands/{brand_id}/enrichment_history?platform=official_site"
    ).json()
    saved = {p["id"]: p for p in body["saved_prompts"]}

    assert set(saved.keys()) == {"is_vegan", "is_organic"}
    # Newer pass wins for label/prompt; use_count reflects total occurrences.
    assert saved["is_vegan"]["prompt"] == "Newer wording"
    assert saved["is_vegan"]["use_count"] == 2
    assert saved["is_vegan"]["last_used_at"] == "20260424T130000Z-bbbb"
    assert saved["is_organic"]["use_count"] == 1
    # Sorted newest-first by last_used_at.
    assert [p["id"] for p in body["saved_prompts"]] == ["is_vegan", "is_organic"]


def test_history_aggregates_across_sources_within_brand(client, tmp_repo):
    """Two official_site sources under one brand both contribute prompts."""
    brand = client.post("/api/brands", json={"name": "MultiSource"}).json()
    bid = brand["id"]

    def add_source_with_enrichment(suffix, enr_id, prompts):
        src = client.post(
            f"/api/brands/{bid}/sources",
            json={"platform": "official_site", "name": f"src-{suffix}", "spec": {
                "brand_url": f"https://example.test/{suffix}",
                "section": "mens", "categories": ["x"], "max_products": 1,
            }},
        ).json()
        run_id = f"20260424T1000{suffix}Z"
        runs_dir = tmp_repo._runs_dir(bid, src["id"])
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / f"{run_id}.json").write_text(json.dumps({
            "_status": "ok", "_meta": {"platform": "official_site"}, "records": [],
        }))
        _write_enrichment(runs_dir, run_id, enr_id, freeform=prompts)

    add_source_with_enrichment("01", "20260424T120000Z-aaaa", [
        {"id": "q_a", "label": "A?", "prompt": "first source"},
    ])
    add_source_with_enrichment("02", "20260424T130000Z-bbbb", [
        {"id": "q_b", "label": "B?", "prompt": "second source"},
    ])

    body = client.get(f"/api/brands/{bid}/enrichment_history?platform=official_site").json()
    ids = {p["id"] for p in body["saved_prompts"]}
    assert ids == {"q_a", "q_b"}


def test_history_filters_by_platform(client, tmp_repo):
    """Asking for shopee history should not return official_site prompts."""
    bid, _, run_id, runs_dir = _seed_brand_with_run(
        client, tmp_repo, name="Mixed", platform="official_site",
    )
    _write_enrichment(runs_dir, run_id, "eid1", freeform=[
        {"id": "official_q", "label": "x", "prompt": "x"},
    ])
    body = client.get(f"/api/brands/{bid}/enrichment_history?platform=shopee").json()
    assert body == {"most_recent": None, "saved_prompts": []}


def test_history_includes_in_progress_passes(client, tmp_repo):
    """Partial files still represent user-entered prompts worth remembering."""
    bid, _, run_id, runs_dir = _seed_brand_with_run(
        client, tmp_repo, name="Partial", platform="official_site",
    )
    _write_enrichment(
        runs_dir, run_id, "20260424T120000Z-aaaa", status="in_progress",
        freeform=[{"id": "q_partial", "label": "P?", "prompt": "partial pass"}],
    )
    body = client.get(f"/api/brands/{bid}/enrichment_history?platform=official_site").json()
    assert body["most_recent"]["freeform_prompts"][0]["id"] == "q_partial"


def test_history_404_for_unknown_brand(client):
    r = client.get("/api/brands/no-such-brand/enrichment_history?platform=official_site")
    assert r.status_code == 404
