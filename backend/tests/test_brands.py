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
        spec={"brand_url": "https://nike.com/sg", "section": "mens", "categories": ["shoes"], "max_products": 10},
    )
    assert source.id  # non-empty
    assert source.brand_id == "nike"
    assert source.platform == "official_site"
    assert source.spec["brand_url"] == "https://nike.com/sg"


def test_list_sources_for_brand(repo):
    repo.create_brand(name="Nike")
    s1 = repo.add_source(brand_id="nike", platform="official_site", spec={"brand_url": "https://nike.com/sg", "section": "mens", "categories": ["shoes"], "max_products": 10})
    s2 = repo.add_source(brand_id="nike", platform="shopee", spec={"shop_url": "https://shopee.sg/nike", "max_products": 50})
    ids = {s.id for s in repo.list_sources("nike")}
    assert ids == {s1.id, s2.id}


def test_get_source_returns_none_if_missing(repo):
    repo.create_brand(name="Nike")
    assert repo.get_source("nike", "does-not-exist") is None


def test_update_source_spec_overwrites(repo):
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", spec={"shop_url": "https://shopee.sg/nike", "max_products": 50})
    repo.update_source_spec("nike", s.id, spec={"shop_url": "https://shopee.sg/nike", "max_products": 100})
    assert repo.get_source("nike", s.id).spec["max_products"] == 100


def test_update_source_missing_raises(repo):
    repo.create_brand(name="Nike")
    with pytest.raises(SourceNotFound):
        repo.update_source_spec("nike", "nope", spec={})


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


def test_list_runs_newest_first_skips_partial(repo, tmp_path):
    import json as _json
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", spec={"shop_url": "x", "max_products": 1})
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
    (runs_dir / "20260413T030000Z.partial.json").write_text(_json.dumps({
        "_status": "in_progress", "_meta": {}, "records": []
    }))

    runs = repo.list_runs("nike", s.id)
    assert [r.id for r in runs] == ["20260413T020000Z", "20260401T000000Z"]
    assert runs[0].status == "cancelled"
    assert runs[0].aggregates["product_count"] == 2
    assert runs[0].aggregates["price_max"] == 10


def test_get_run_payload(repo, tmp_path):
    import json as _json
    repo.create_brand(name="Nike")
    s = repo.add_source(brand_id="nike", platform="shopee", spec={"shop_url": "x", "max_products": 1})
    runs_dir = tmp_path / "nike" / "sources" / s.id / "runs"
    payload = {"_status": "ok", "_meta": {"aggregates": {"product_count": 1}}, "records": [{"item_id": 1}]}
    (runs_dir / "20260401T000000Z.json").write_text(_json.dumps(payload))
    assert repo.get_run_payload("nike", s.id, "20260401T000000Z") == payload
    assert repo.get_run_payload("nike", s.id, "nope") is None
