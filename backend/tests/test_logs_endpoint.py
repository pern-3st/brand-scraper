def test_get_run_logs_endpoint_reads_jsonl(client, tmp_repo):
    brand = client.post("/api/brands", json={"name": "LogTest"}).json()
    src = client.post(
        f"/api/brands/{brand['id']}/sources",
        json={"platform": "shopee", "name": "Shopee X", "spec": {"shop_url": "https://shopee.sg/x", "max_products": 1}},
    ).json()

    # Seed a run file + log file directly via the (tmp-rooted) repo.
    run_id = "20260422T150000Z"
    runs_dir = tmp_repo._runs_dir(brand["id"], src["id"])
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text('{"_status":"ok","_meta":{},"records":[]}')
    tmp_repo.log_path(brand["id"], src["id"], run_id).write_text(
        '{"message":"hello","level":"info"}\n'
        '{"message":"done","level":"success"}\n'
    )

    r = client.get(f"/api/brands/{brand['id']}/sources/{src['id']}/runs/{run_id}/logs")
    assert r.status_code == 200
    assert r.json() == [
        {"message": "hello", "level": "info"},
        {"message": "done", "level": "success"},
    ]


def test_get_run_logs_run_without_log_file_returns_empty(client, tmp_repo):
    """Run exists but no `.log.jsonl` sidecar → 200 with []."""
    brand = client.post("/api/brands", json={"name": "LogEmpty"}).json()
    src = client.post(
        f"/api/brands/{brand['id']}/sources",
        json={"platform": "shopee", "name": "Shopee Y", "spec": {"shop_url": "https://shopee.sg/y", "max_products": 1}},
    ).json()
    run_id = "20260422T160000Z"
    runs_dir = tmp_repo._runs_dir(brand["id"], src["id"])
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text('{"_status":"ok","_meta":{},"records":[]}')

    r = client.get(f"/api/brands/{brand['id']}/sources/{src['id']}/runs/{run_id}/logs")
    assert r.status_code == 200
    assert r.json() == []


def test_get_run_logs_missing_run_returns_404(client):
    brand = client.post("/api/brands", json={"name": "LogMissing"}).json()
    src = client.post(
        f"/api/brands/{brand['id']}/sources",
        json={"platform": "shopee", "name": "Shopee Z", "spec": {"shop_url": "https://shopee.sg/z", "max_products": 1}},
    ).json()
    r = client.get(f"/api/brands/{brand['id']}/sources/{src['id']}/runs/nope/logs")
    assert r.status_code == 404


def test_get_run_logs_missing_source_returns_404(client):
    brand = client.post("/api/brands", json={"name": "LogNoSrc"}).json()
    r = client.get(f"/api/brands/{brand['id']}/sources/nope/runs/whatever/logs")
    assert r.status_code == 404
