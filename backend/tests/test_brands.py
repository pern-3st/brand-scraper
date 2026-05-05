import json

from app.brands import slugify_brand_name


def test_slugify_lowercases_and_hyphenates():
    assert slugify_brand_name("Nike") == "nike"
    assert slugify_brand_name("Lovisa Jewellery") == "lovisa-jewellery"


def test_slugify_strips_punctuation_and_collapses():
    assert slugify_brand_name("H&M") == "h-m"
    assert slugify_brand_name("  Off—White  ") == "off-white"


def test_slugify_rejects_empty_after_normalization():
    import pytest
    with pytest.raises(ValueError):
        slugify_brand_name("!!!")


import pytest
from app.brands import BrandRepo, BrandAlreadyExists


@pytest.fixture
def repo(tmp_path):
    return BrandRepo(root=tmp_path)


def test_create_and_read_brand(repo):
    brand = repo.create_brand(name="Nike")
    assert brand.id == "nike"
    assert brand.name == "Nike"
    assert brand.created_at  # ISO8601

    loaded = repo.get_brand("nike")
    assert loaded == brand


def test_create_brand_rejects_slug_collision(repo):
    repo.create_brand(name="Nike")
    with pytest.raises(BrandAlreadyExists):
        repo.create_brand(name="Nike")  # same slug

    with pytest.raises(BrandAlreadyExists):
        repo.create_brand(name="NIKE")  # collides on slug


def test_list_brands_returns_created_brands_sorted(repo):
    repo.create_brand(name="Zara")
    repo.create_brand(name="Adidas")
    repo.create_brand(name="Nike")
    ids = [b.id for b in repo.list_brands()]
    assert ids == ["adidas", "nike", "zara"]


def test_get_brand_returns_none_if_missing(repo):
    assert repo.get_brand("does-not-exist") is None


from app.brands import SourceNotFound


def test_add_source_returns_generated_id(repo):
    repo.create_brand(name="Nike")
    source = repo.add_source(
        brand_id="nike",
        platform="official_site",
        name="Nike Official",
        spec={"brand_url": "https://nike.com/sg", "section": "mens", "categories": ["shoes"], "max_products": 10},
    )
    assert source.id  # non-empty
    assert source.brand_id == "nike"
    assert source.platform == "official_site"
    assert source.spec["brand_url"] == "https://nike.com/sg"


def test_list_sources_for_brand(repo):
    repo.create_brand(name="Nike")
    s1 = repo.add_source(brand_id="nike", platform="official_site", name="Nike Official", spec={"brand_url": "https://nike.com/sg", "section": "mens", "categories": ["shoes"], "max_products": 10})
    s2 = repo.add_source(brand_id="nike", platform="shopee", name="Nike Shopee", spec={"shop_url": "https://shopee.sg/nike", "max_products": 50})
    ids = {s.id for s in repo.list_sources("nike")}
    assert ids == {s1.id, s2.id}


def test_get_source_returns_none_if_missing(repo):
    repo.create_brand(name="Nike")
    assert repo.get_source("nike", "does-not-exist") is None


def test_update_source_spec_overwrites(repo):
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", name="Nike Shopee", spec={"shop_url": "https://shopee.sg/nike", "max_products": 50})
    repo.update_source("nike", s.id, spec={"shop_url": "https://shopee.sg/nike", "max_products": 100})
    assert repo.get_source("nike", s.id).spec["max_products"] == 100


def test_update_source_missing_raises(repo):
    repo.create_brand(name="Nike")
    with pytest.raises(SourceNotFound):
        repo.update_source("nike", "nope", spec={})


from app.brands import compute_run_aggregates


def test_aggregates_official_site_records():
    records = [
        {"product_name": "A", "category": "shoes", "price": 42.0},
        {"product_name": "B", "category": "shoes", "price": 189.0},
        {"product_name": "C", "category": "bags",  "price": 30.0},
        {"product_name": "D", "category": "bags",  "price": 150.0},
        {"product_name": "E", "category": "bags",  "price": None},
    ]
    agg = compute_run_aggregates(records=records)
    assert agg == {
        "product_count": 5,
        "price_min": 30.0,
        "price_max": 189.0,
        "category_count": 2,
    }


def test_aggregates_shopee_records():
    # Shopee records carry no `category`; category_count naturally falls to 0.
    records = [
        {"product_name": "A", "item_id": 1, "price": 20.0},
        {"product_name": "B", "item_id": 2, "price": 50.0},
        {"product_name": "C", "item_id": 3, "price": None},
    ]
    agg = compute_run_aggregates(records=records)
    assert agg == {
        "product_count": 3,
        "price_min": 20.0,
        "price_max": 50.0,
        "category_count": 0,
    }


def test_aggregates_empty():
    agg = compute_run_aggregates(records=[])
    assert agg == {
        "product_count": 0,
        "price_min": None,
        "price_max": None,
        "category_count": 0,
    }


def test_list_runs_includes_partial(repo, tmp_path):
    import json as _json
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", name="Nike Shopee", spec={"shop_url": "x", "max_products": 1})
    runs_dir = tmp_path / "nike" / "sources" / s.id / "runs"
    (runs_dir / "20260401T000000Z.json").write_text(_json.dumps({
        "_status": "ok",
        "_meta": {"aggregates": {"product_count": 1, "price_min": 1, "price_max": 1, "category_count": None}},
        "records": [],
    }))
    (runs_dir / "20260413T020000Z.json").write_text(_json.dumps({
        "_status": "cancelled",
        "_meta": {"aggregates": {"product_count": 2, "price_min": 5, "price_max": 10, "category_count": None}},
        "records": [],
    }))
    # Realistic error partial: `meta["aggregates"]` is missing because
    # the runner sets it AFTER the async-for loop completes — an exception
    # raised mid-loop reaches `except Exception` before that line runs.
    # (See runner.py:90-141.)
    (runs_dir / "20260413T030000Z.partial.json").write_text(_json.dumps({
        "_status": "error",
        "_meta": {"error": "boom"},
        "records": [],
    }))

    runs = repo.list_runs("nike", s.id)
    assert [r.id for r in runs] == ["20260413T030000Z", "20260413T020000Z", "20260401T000000Z"]
    assert runs[0].status == "error"
    # All aggregate keys default to None when `_meta.aggregates` is absent.
    assert runs[0].aggregates == {k: None for k in ("product_count", "price_min", "price_max", "category_count")}
    assert runs[1].status == "cancelled"
    assert runs[2].status == "ok"


def test_list_runs_partial_without_final_version_wins(repo, tmp_path):
    """If both `<id>.json` and `<id>.partial.json` exist (shouldn't happen,
    but be defensive), prefer the final one."""
    import json as _json
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", name="Nike Shopee", spec={"shop_url": "x", "max_products": 1})
    runs_dir = tmp_path / "nike" / "sources" / s.id / "runs"
    (runs_dir / "20260501T000000Z.json").write_text(_json.dumps({
        "_status": "ok", "_meta": {"aggregates": {}}, "records": [],
    }))
    (runs_dir / "20260501T000000Z.partial.json").write_text(_json.dumps({
        "_status": "in_progress", "_meta": {"aggregates": {}}, "records": [],
    }))
    runs = repo.list_runs("nike", s.id)
    assert len(runs) == 1
    assert runs[0].status == "ok"


def test_get_run_payload_falls_back_to_partial(repo, tmp_path):
    import json as _json
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", name="Nike Shopee", spec={"shop_url": "x", "max_products": 1})
    runs_dir = tmp_path / "nike" / "sources" / s.id / "runs"
    payload = {"_status": "error", "_meta": {"error": "boom"}, "records": []}
    (runs_dir / "20260422T100000Z.partial.json").write_text(_json.dumps(payload))
    assert repo.get_run_payload("nike", s.id, "20260422T100000Z") == payload


def test_delete_run_removes_log_file(repo, tmp_path):
    import json as _json
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", name="Nike Shopee", spec={"shop_url": "x", "max_products": 1})
    runs_dir = tmp_path / "nike" / "sources" / s.id / "runs"
    (runs_dir / "20260422T110000Z.json").write_text(_json.dumps({"_status": "ok", "_meta": {}, "records": []}))
    (runs_dir / "20260422T110000Z.log.jsonl").write_text('{"message":"x","level":"info"}\n')

    assert repo.delete_run("nike", s.id, "20260422T110000Z") is True
    assert not (runs_dir / "20260422T110000Z.json").exists()
    assert not (runs_dir / "20260422T110000Z.log.jsonl").exists()


def test_delete_run_removes_partial(repo, tmp_path):
    import json as _json
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", name="Nike Shopee", spec={"shop_url": "x", "max_products": 1})
    runs_dir = tmp_path / "nike" / "sources" / s.id / "runs"
    (runs_dir / "20260422T120000Z.partial.json").write_text(_json.dumps({"_status": "error", "_meta": {}, "records": []}))
    assert repo.delete_run("nike", s.id, "20260422T120000Z") is True
    assert not (runs_dir / "20260422T120000Z.partial.json").exists()


def test_get_run_payload(repo, tmp_path):
    import json as _json
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", name="Nike Shopee", spec={"shop_url": "x", "max_products": 1})
    runs_dir = tmp_path / "nike" / "sources" / s.id / "runs"
    payload = {"_status": "ok", "_meta": {"aggregates": {"product_count": 1}}, "records": [{"item_id": 1}]}
    (runs_dir / "20260401T000000Z.json").write_text(_json.dumps(payload))
    assert repo.get_run_payload("nike", s.id, "20260401T000000Z") == payload
    assert repo.get_run_payload("nike", s.id, "nope") is None


def test_log_path_creates_runs_dir(repo):
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", name="Nike Shopee", spec={"shop_url": "x", "max_products": 1})
    p = repo.log_path("nike", s.id, "20260422T000000Z")
    assert p.name == "20260422T000000Z.log.jsonl"
    assert p.parent.name == "runs"
    assert p.parent.exists()


def test_get_run_logs_reads_jsonl(repo, tmp_path):
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", name="Nike Shopee", spec={"shop_url": "x", "max_products": 1})
    log_file = tmp_path / "nike" / "sources" / s.id / "runs" / "20260422T000000Z.log.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(
        '{"message": "a", "level": "info"}\n'
        '{"message": "b", "level": "warning"}\n'
    )
    logs = repo.get_run_logs("nike", s.id, "20260422T000000Z")
    assert logs == [
        {"message": "a", "level": "info"},
        {"message": "b", "level": "warning"},
    ]


def test_get_run_logs_missing_returns_empty(repo):
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", name="Nike Shopee", spec={"shop_url": "x", "max_products": 1})
    assert repo.get_run_logs("nike", s.id, "does-not-exist") == []


def test_enriched_field_map_aggregates_across_passes(repo):
    brand = repo.create_brand(name="Acme")
    source = repo.add_source(
        brand_id=brand.id, platform="official_site", name="Acme Official", spec={"brand_url": "https://acme.test"}
    )
    run_id = "20260504T000000Z"
    edir = repo._enrichments_dir(brand.id, source.id, run_id)
    edir.mkdir(parents=True, exist_ok=True)
    (edir / "pass_a.json").write_text(json.dumps({
        "_status": "ok",
        "_meta": {"platform": "official_site"},
        "results": [
            {"product_key": "p1", "values": {"description": "x"}, "errors": {}},
            {"product_key": "p2", "values": {}, "errors": {"_all": "boom"}},
        ],
    }))
    (edir / "pass_b.partial.json").write_text(json.dumps({
        "_status": "in_progress",
        "_meta": {"platform": "official_site"},
        "results": [
            {"product_key": "p1", "values": {"rating": 4.5}, "errors": {}},
            {"product_key": "p3", "values": {"description": None}, "errors": {}},
        ],
    }))

    out = repo.enriched_field_map(brand.id, source.id, run_id)

    assert out == {
        "p1": {"description", "rating"},
    }


def test_enriched_field_map_returns_empty_when_no_runs(repo):
    brand = repo.create_brand(name="Acme")
    source = repo.add_source(
        brand_id=brand.id, platform="official_site", name="Acme Official", spec={"brand_url": "https://acme.test"}
    )
    assert repo.enriched_field_map(brand.id, source.id, "nonexistent_run") == {}


def test_add_source_persists_name(repo):
    repo.create_brand(name="Nike")
    s = repo.add_source(
        brand_id="nike",
        platform="shopee",
        name="Shopee SG",
        spec={"shop_url": "https://shopee.sg/nike", "max_products": 50},
    )
    assert s.name == "Shopee SG"
    reloaded = repo.get_source("nike", s.id)
    assert reloaded.name == "Shopee SG"


def test_update_source_can_change_name(repo):
    repo.create_brand(name="Nike")
    s = repo.add_source(
        brand_id="nike", platform="shopee", name="Shopee SG",
        spec={"shop_url": "https://shopee.sg/nike", "max_products": 50},
    )
    repo.update_source(
        "nike", s.id, name="Shopee Singapore", spec=s.spec,
    )
    assert repo.get_source("nike", s.id).name == "Shopee Singapore"


def test_create_source_endpoint_requires_name(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, runner

    repo = BrandRepo(root=tmp_path)
    repo.create_brand(name="Nike")
    monkeypatch.setattr(runner, "_repo", repo)

    client = TestClient(main.app)
    resp = client.post(
        "/api/brands/nike/sources",
        json={
            "platform": "shopee",
            "spec": {"shop_url": "https://shopee.sg/nike", "max_products": 50},
        },
    )
    assert resp.status_code == 422

    resp = client.post(
        "/api/brands/nike/sources",
        json={
            "platform": "shopee",
            "name": "Shopee SG",
            "spec": {"shop_url": "https://shopee.sg/nike", "max_products": 50},
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Shopee SG"


def test_update_source_endpoint_can_change_name(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, runner

    repo = BrandRepo(root=tmp_path)
    repo.create_brand(name="Nike")
    s = repo.add_source(
        brand_id="nike", platform="shopee", name="Shopee SG",
        spec={"shop_url": "https://shopee.sg/nike", "max_products": 50},
    )
    monkeypatch.setattr(runner, "_repo", repo)

    client = TestClient(main.app)
    resp = client.patch(
        f"/api/brands/nike/sources/{s.id}",
        json={"name": "Shopee Singapore"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Shopee Singapore"
    assert repo.get_source("nike", s.id).name == "Shopee Singapore"
    assert repo.get_source("nike", s.id).spec["shop_url"] == "https://shopee.sg/nike"


def test_backfill_fills_missing_name_from_shop_url(tmp_path):
    brand_dir = tmp_path / "nike"
    (brand_dir / "sources" / "abc12345" / "runs").mkdir(parents=True)
    (brand_dir / "brand.json").write_text(json.dumps({
        "id": "nike", "name": "Nike", "created_at": "2026-01-01T00:00:00Z",
    }))
    (brand_dir / "sources" / "abc12345" / "source.json").write_text(json.dumps({
        "id": "abc12345",
        "brand_id": "nike",
        "platform": "shopee",
        "spec": {"shop_url": "https://shopee.sg/nike", "max_products": 50},
        "created_at": "2026-01-01T00:00:00Z",
    }))

    repo = BrandRepo(root=tmp_path)
    s = repo.get_source("nike", "abc12345")
    assert s.name == "https://shopee.sg/nike"


def test_backfill_fills_missing_name_from_brand_url(tmp_path):
    brand_dir = tmp_path / "nike"
    (brand_dir / "sources" / "def67890" / "runs").mkdir(parents=True)
    (brand_dir / "brand.json").write_text(json.dumps({
        "id": "nike", "name": "Nike", "created_at": "2026-01-01T00:00:00Z",
    }))
    (brand_dir / "sources" / "def67890" / "source.json").write_text(json.dumps({
        "id": "def67890",
        "brand_id": "nike",
        "platform": "official_site",
        "spec": {
            "brand_url": "https://nike.com/sg",
            "section": "mens",
            "categories": ["shoes"],
            "max_products": 10,
        },
        "created_at": "2026-01-01T00:00:00Z",
    }))

    repo = BrandRepo(root=tmp_path)
    assert repo.get_source("nike", "def67890").name == "https://nike.com/sg"


def test_backfill_is_idempotent(tmp_path):
    repo = BrandRepo(root=tmp_path)
    repo.create_brand(name="Nike")
    s = repo.add_source(
        brand_id="nike", platform="shopee", name="Shopee SG",
        spec={"shop_url": "x", "max_products": 1},
    )
    repo2 = BrandRepo(root=tmp_path)
    assert repo2.get_source("nike", s.id).name == "Shopee SG"


def test_update_source_leaves_name_when_omitted(repo):
    repo.create_brand(name="Nike")
    s = repo.add_source(
        brand_id="nike", platform="shopee", name="Shopee SG",
        spec={"shop_url": "https://shopee.sg/nike", "max_products": 50},
    )
    repo.update_source("nike", s.id, spec={"shop_url": "x", "max_products": 1})
    assert repo.get_source("nike", s.id).name == "Shopee SG"
