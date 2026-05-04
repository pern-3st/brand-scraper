"""Retroactive enrichment-log endpoint + BrandRepo.get_enrichment_logs.

Tests both the repo method (unit) and the route (integration), mirroring
the shape of tests/test_logs_endpoint.py for run-level logs.
"""
import json

from app.brands import ENRICHMENT_DIR_SUFFIX


def _seed_brand_source_run(client, tmp_repo, platform="official_site"):
    brand = client.post("/api/brands", json={"name": "LogEnr"}).json()
    src = client.post(
        f"/api/brands/{brand['id']}/sources",
        json={"platform": platform, "spec": {
            "brand_url": "https://logenr.test",
            "section": "mens",
            "categories": ["shoes"],
            "max_products": 1,
        }},
    ).json()
    run_id = "20260424T130000Z"
    runs_dir = tmp_repo._runs_dir(brand["id"], src["id"])
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(json.dumps({
        "_status": "ok", "_meta": {"platform": platform}, "records": [],
    }))
    return brand["id"], src["id"], run_id, runs_dir


def _seed_enrichment(runs_dir, run_id, enr_id, log_lines=None):
    edir = runs_dir / f"{run_id}{ENRICHMENT_DIR_SUFFIX}"
    edir.mkdir(exist_ok=True)
    (edir / f"{enr_id}.json").write_text(json.dumps({
        "_status": "ok", "_meta": {}, "results": [],
    }))
    if log_lines is not None:
        (edir / f"{enr_id}.log.jsonl").write_text(
            "\n".join(json.dumps(l) for l in log_lines) + ("\n" if log_lines else "")
        )


def test_repo_get_enrichment_logs_reads_jsonl(client, tmp_repo):
    bid, sid, rid, rdir = _seed_brand_source_run(client, tmp_repo)
    _seed_enrichment(rdir, rid, "enr1", log_lines=[
        {"message": "hi", "level": "info"},
        {"message": "boom", "level": "error"},
    ])
    logs = tmp_repo.get_enrichment_logs(bid, sid, rid, "enr1")
    assert logs == [
        {"message": "hi", "level": "info"},
        {"message": "boom", "level": "error"},
    ]


def test_repo_get_enrichment_logs_missing_sidecar_returns_empty(client, tmp_repo):
    bid, sid, rid, rdir = _seed_brand_source_run(client, tmp_repo)
    _seed_enrichment(rdir, rid, "enr1", log_lines=None)
    assert tmp_repo.get_enrichment_logs(bid, sid, rid, "enr1") == []


# --- route -----------------------------------------------------------------


def test_get_enrichment_logs_endpoint_reads_jsonl(client, tmp_repo):
    bid, sid, rid, rdir = _seed_brand_source_run(client, tmp_repo)
    _seed_enrichment(rdir, rid, "enr1", log_lines=[
        {"message": "hello", "level": "info"},
        {"message": "warn", "level": "warning"},
    ])
    r = client.get(
        f"/api/brands/{bid}/sources/{sid}/runs/{rid}/enrichments/enr1/logs"
    )
    assert r.status_code == 200
    assert r.json() == [
        {"message": "hello", "level": "info"},
        {"message": "warn", "level": "warning"},
    ]


def test_get_enrichment_logs_endpoint_empty_when_no_sidecar(client, tmp_repo):
    bid, sid, rid, rdir = _seed_brand_source_run(client, tmp_repo)
    _seed_enrichment(rdir, rid, "enr1", log_lines=None)
    r = client.get(
        f"/api/brands/{bid}/sources/{sid}/runs/{rid}/enrichments/enr1/logs"
    )
    assert r.status_code == 200
    assert r.json() == []


def test_get_enrichment_logs_404_missing_source(client):
    brand = client.post("/api/brands", json={"name": "x"}).json()
    r = client.get(
        f"/api/brands/{brand['id']}/sources/nope/runs/whatever/enrichments/enr1/logs"
    )
    assert r.status_code == 404


def test_get_enrichment_logs_404_missing_run(client, tmp_repo):
    bid, sid, _, _ = _seed_brand_source_run(client, tmp_repo)
    r = client.get(
        f"/api/brands/{bid}/sources/{sid}/runs/nope/enrichments/enr1/logs"
    )
    assert r.status_code == 404


def test_get_enrichment_logs_404_missing_enrichment(client, tmp_repo):
    bid, sid, rid, _ = _seed_brand_source_run(client, tmp_repo)
    # Run exists, no enrichment seeded.
    r = client.get(
        f"/api/brands/{bid}/sources/{sid}/runs/{rid}/enrichments/nope/logs"
    )
    assert r.status_code == 404
