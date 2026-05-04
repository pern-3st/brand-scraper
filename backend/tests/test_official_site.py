"""Tests for the official-site scraper schema plumbing.

Focuses on the glue between our Pydantic models and browser_use's
extraction-schema validator. See
docs/plans/2026-04-22-official-site-scraper-reliability-design.md.
"""
from __future__ import annotations

import json

import pytest

from app.platforms.official_site import (
    EXTRACTION_SCHEMA,
    PageExtraction,
    ProductExtraction,
    _compile_extraction_schema,
    _dedupe_by_url,
    canonical_url,
)


def _contains(node: object, key: str) -> bool:
    """True if `key` appears anywhere in the nested structure."""
    if isinstance(node, dict):
        if key in node:
            return True
        return any(_contains(v, key) for v in node.values())
    if isinstance(node, list):
        return any(_contains(v, key) for v in node)
    return False


def test_compile_strips_unsupported_keywords():
    """After compilation, the schema must contain no `$ref`, `$defs`, or
    `anyOf` — all three are rejected by browser_use's
    `schema_dict_to_pydantic_model`."""
    raw = PageExtraction.model_json_schema()
    # Sanity: Pydantic should emit both $defs (nested model) and anyOf
    # (Optional fields), so we're actually testing something.
    assert _contains(raw, "$defs"), "precondition: Pydantic should emit $defs"
    assert _contains(raw, "anyOf"), "precondition: Pydantic should emit anyOf for Optional"

    compiled = _compile_extraction_schema(raw)
    assert not _contains(compiled, "$ref")
    assert not _contains(compiled, "$defs")
    assert not _contains(compiled, "anyOf")


def test_compile_marks_optional_fields_nullable():
    """Pydantic `Optional[X]` must round-trip as `nullable: true` so
    browser_use wraps the type with `| None`."""
    compiled = _compile_extraction_schema(PageExtraction.model_json_schema())
    product_props = compiled["properties"]["products"]["items"]["properties"]
    assert product_props["price"].get("nullable") is True
    assert product_props["price"].get("type") == "number"
    assert product_props["url"].get("nullable") is True
    assert product_props["url"].get("type") == "string"


def test_compile_does_not_mutate_input():
    raw = PageExtraction.model_json_schema()
    before = json.dumps(raw, sort_keys=True)
    _compile_extraction_schema(raw)
    after = json.dumps(raw, sort_keys=True)
    assert before == after


def test_extraction_schema_accepted_by_browser_use():
    """The live EXTRACTION_SCHEMA must survive browser_use's schema
    validator — this is the whole point of inlining."""
    from browser_use.tools.extraction.schema_utils import schema_dict_to_pydantic_model

    model = schema_dict_to_pydantic_model(EXTRACTION_SCHEMA)
    # Round-trip a payload through the generated model to confirm fields
    # survived inlining with the right types.
    instance = model.model_validate(
        {
            "found": True,
            "currency": "$",
            "products": [
                {
                    "name": "Slim fit jean",
                    "price": 49.99,
                    "original_price": 79.99,
                    "url": "https://example.com/p/1",
                    "image_url": "https://example.com/img/1.jpg",
                    "is_sold_out": False,
                }
            ],
        }
    )
    assert instance.found is True
    assert instance.products[0].name == "Slim fit jean"


def test_page_result_pagination_end_mechanism():
    from app.platforms.official_site import PageResult, Pagination
    pr = PageResult(pagination=Pagination(mechanism="end"))
    assert pr.pagination.mechanism == "end"
    assert pr.pagination.url_pattern is None
    assert pr.currency == ""


def test_page_result_accepts_url_pattern():
    from app.platforms.official_site import PageResult, Pagination
    pr = PageResult(
        currency="$",
        pagination=Pagination(mechanism="url_param", url_pattern="?page={n}"),
    )
    assert pr.pagination.url_pattern == "?page={n}"


def test_nav_result_minimal():
    from app.platforms.official_site import NavResult
    nr = NavResult(found=True)
    assert nr.found is True


def test_build_page_hint_url_pattern():
    from app.platforms.official_site import Pagination, _build_page_hint
    hint = _build_page_hint(
        page_index=3,
        previous=Pagination(mechanism="url_param", url_pattern="?page={n}"),
    )
    assert "?page=3" in hint
    assert "Next" in hint  # fallback instruction still present


def test_build_page_hint_next_button():
    from app.platforms.official_site import Pagination, _build_page_hint
    hint = _build_page_hint(
        page_index=2,
        previous=Pagination(mechanism="next_button"),
    )
    assert "Next" in hint
    assert "?page=" not in hint


def test_build_page_hint_first_page_returns_empty():
    from app.platforms.official_site import _build_page_hint
    assert _build_page_hint(page_index=1, previous=None) == ""


class TestCanonicalUrl:
    def test_strips_query_and_fragment(self):
        assert canonical_url("https://www2.hm.com/en_sg/productpage.123.html?color=red#reviews") == \
            "https://www2.hm.com/en_sg/productpage.123.html"

    def test_lowercases_host_preserves_path_case(self):
        assert canonical_url("https://WWW2.HM.COM/en_SG/ProductPage.123.html") == \
            "https://www2.hm.com/en_SG/ProductPage.123.html"

    def test_removes_trailing_slash(self):
        assert canonical_url("https://example.com/p/abc/") == "https://example.com/p/abc"

    def test_preserves_root_slash(self):
        # "/" is the root path; canonicalising it away would change the URL's meaning.
        assert canonical_url("https://example.com/") == "https://example.com/"

    def test_resolves_relative_url_against_base(self):
        base = "https://www2.hm.com/en_sg/kids/tops.html"
        assert canonical_url("/en_sg/productpage.123.html?a=1", base=base) == \
            "https://www2.hm.com/en_sg/productpage.123.html"

    def test_returns_empty_for_none_or_blank(self):
        assert canonical_url(None) == ""
        assert canonical_url("") == ""
        assert canonical_url("   ") == ""

    def test_returns_empty_for_malformed(self):
        # No scheme, no base — cannot canonicalize.
        assert canonical_url("not a url") == ""


class TestDedupeByUrl:
    def _product(self, url: str | None, name: str = "T"):
        return ProductExtraction(name=name, url=url, price=1.0)

    def test_drops_duplicate_canonical_urls(self):
        p1 = self._product("https://x.com/p/1.html?color=red")
        p2 = self._product("https://x.com/p/1.html?color=blue")
        p3 = self._product("https://x.com/p/2.html")
        result = _dedupe_by_url([p1, p2, p3])
        # First-seen wins, and the kept record's URL is rewritten to the
        # canonical form (query stripped).
        assert [p.url for p in result] == [
            "https://x.com/p/1.html",
            "https://x.com/p/2.html",
        ]

    def test_drops_records_without_url(self):
        p1 = self._product(None)
        p2 = self._product("")
        p3 = self._product("https://x.com/p/1.html")
        result = _dedupe_by_url([p1, p2, p3])
        assert len(result) == 1
        assert result[0].url == "https://x.com/p/1.html"

    def test_preserves_order_of_first_occurrence(self):
        p1 = self._product("https://x.com/a.html")
        p2 = self._product("https://x.com/b.html")
        p3 = self._product("https://x.com/a.html")  # dup
        p4 = self._product("https://x.com/c.html")
        result = _dedupe_by_url([p1, p2, p3, p4])
        assert [p.url for p in result] == [p1.url, p2.url, p4.url]

    def test_resolves_relative_urls_with_base(self):
        # H&M-style: extract returns site-relative paths. Without `base`,
        # every record is unparseable and dropped; with `base`, they
        # resolve to absolute URLs and dedupe correctly.
        p1 = self._product("/en_sg/productpage.111.html?color=red")
        p2 = self._product("/en_sg/productpage.111.html")  # dup of p1
        p3 = self._product("/en_sg/productpage.222.html")
        result = _dedupe_by_url([p1, p2, p3], base="https://www2.hm.com/")
        assert [p.url for p in result] == [
            "https://www2.hm.com/en_sg/productpage.111.html",
            "https://www2.hm.com/en_sg/productpage.222.html",
        ]

    def test_without_base_relative_urls_are_dropped(self):
        # Regression guard: the real failure mode. Without `base=`, the
        # agent's relative URLs canonicalize to "" and every product is
        # dropped as no_url.
        p1 = self._product("/en_sg/productpage.111.html")
        p2 = self._product("/en_sg/productpage.222.html")
        assert _dedupe_by_url([p1, p2]) == []


# ---- Orchestrator loop tests ----
import asyncio

from app.platforms import official_site
from app.platforms.official_site import (
    NavResult,
    Pagination,
    PageResult,
    _scrape_category,
)


def _page(mech: str, products: list[ProductExtraction], url_pattern=None) -> tuple[PageResult, list[ProductExtraction]]:
    return (
        PageResult(currency="$", pagination=Pagination(mechanism=mech, url_pattern=url_pattern)),
        products,
    )


async def test_orchestrator_stops_on_end(monkeypatch):
    calls = []

    async def fake_nav(**kwargs):
        return NavResult(found=True)

    async def fake_page(*, page_index, **kwargs):
        calls.append(page_index)
        mech = "end" if page_index == 2 else "next_button"
        prods = [ProductExtraction(name=f"p{page_index}", price=10.0, url=f"https://ex.com/p{page_index}")]
        return _page(mech, prods)

    monkeypatch.setattr(official_site, "_navigate_to_category", fake_nav)
    monkeypatch.setattr(official_site, "_extract_page", fake_page)

    records = await _scrape_category(
        browser=None, llm=None,
        brand_url="https://ex.com", section="womens", category="shirts",
        max_products=100, cancel_event=asyncio.Event(),
    )
    assert calls == [1, 2]
    assert len(records) == 2


async def test_orchestrator_stops_on_budget(monkeypatch):
    calls = []

    async def fake_nav(**kwargs):
        return NavResult(found=True)

    async def fake_page(*, page_index, **kwargs):
        calls.append(page_index)
        prods = [
            ProductExtraction(name=f"page{page_index}_p{i}", price=10.0,
                              url=f"https://ex.com/page{page_index}/p{i}")
            for i in range(2)
        ]
        return _page("next_button", prods)

    monkeypatch.setattr(official_site, "_navigate_to_category", fake_nav)
    monkeypatch.setattr(official_site, "_extract_page", fake_page)

    records = await _scrape_category(
        browser=None, llm=None,
        brand_url="https://ex.com", section="womens", category="shirts",
        max_products=3, cancel_event=asyncio.Event(),
    )
    # Page 1 runs (total=0 < 3), yields 2 → total=2.
    # Page 2 runs (total=2 < 3), yields 2 → total=4, overshoots budget.
    # Loop exits because 4 >= 3 — over-budget products are kept, not dropped.
    assert calls == [1, 2]
    assert len(records) == 4


async def test_orchestrator_returns_empty_when_navigator_not_found(monkeypatch):
    async def fake_nav(**kwargs):
        return NavResult(found=False)

    async def fake_page(**kwargs):
        raise AssertionError("page agent must not run when nav failed")

    monkeypatch.setattr(official_site, "_navigate_to_category", fake_nav)
    monkeypatch.setattr(official_site, "_extract_page", fake_page)

    records = await _scrape_category(
        browser=None, llm=None,
        brand_url="https://ex.com", section="womens", category="shirts",
        max_products=50, cancel_event=asyncio.Event(),
    )
    assert records == []


async def test_orchestrator_breaks_on_consecutive_zero_yield_pages(monkeypatch):
    """Guard against silent agent failures: if two consecutive pages
    produce no new unique URLs, stop looping even if the agent keeps
    reporting a non-end pagination mechanism."""
    calls = []

    async def fake_nav(**kwargs):
        return NavResult(found=True)

    async def fake_page(*, page_index, **kwargs):
        calls.append(page_index)
        if page_index == 1:
            prods = [ProductExtraction(name="a", price=1.0, url="https://ex.com/a")]
        else:
            # Same URL as page 1 → zero new unique products.
            prods = [ProductExtraction(name="a", price=1.0, url="https://ex.com/a")]
        return _page("next_button", prods)

    monkeypatch.setattr(official_site, "_navigate_to_category", fake_nav)
    monkeypatch.setattr(official_site, "_extract_page", fake_page)

    records = await _scrape_category(
        browser=None, llm=None,
        brand_url="https://ex.com", section="womens", category="shirts",
        max_products=100, cancel_event=asyncio.Event(),
    )
    # Page 1 yields 1 new. Page 2 yields 0 (streak=1). Page 3 yields 0 (streak=2) → break.
    assert calls == [1, 2, 3]
    assert len(records) == 1  # only one unique URL across all three pages


# ---- History-backed extraction reader ----
from types import SimpleNamespace

from app.platforms.official_site import _extractions_from_history


def _mk_action_result(data: dict | None):
    """Mimic an ActionResult with (or without) a structured extraction payload."""
    if data is None:
        return SimpleNamespace(metadata=None)
    return SimpleNamespace(
        metadata={"extraction_result": {"data": data, "is_partial": False}}
    )


def _mk_history(*step_results):
    """Build an object quacking like AgentHistoryList for our reader."""
    steps = [SimpleNamespace(result=list(results)) for results in step_results]
    return SimpleNamespace(history=steps)


def test_extractions_from_history_pulls_structured_data():
    payload = {
        "found": True,
        "currency": "S$",
        "products": [
            {"name": "Tee", "price": 7.9, "url": "/p/1", "image_url": "/i/1.jpg",
             "original_price": None, "is_sold_out": False},
        ],
    }
    history = _mk_history([_mk_action_result(payload)])
    got = _extractions_from_history(history)
    assert len(got) == 1
    assert got[0].currency == "S$"
    assert got[0].products[0].name == "Tee"


def test_extractions_from_history_ignores_non_extract_steps():
    payload = {
        "found": True,
        "currency": "",
        "products": [{"name": "A", "price": 1.0, "url": "/a",
                      "image_url": None, "original_price": None, "is_sold_out": False}],
    }
    history = _mk_history(
        [_mk_action_result(None)],           # e.g. a scroll step
        [_mk_action_result(payload)],        # an extract step
        [_mk_action_result(None)],           # a click step
    )
    got = _extractions_from_history(history)
    assert len(got) == 1
    assert got[0].products[0].name == "A"


def test_extractions_from_history_handles_multiple_extracts():
    p1 = {"found": True, "currency": "$", "products": [
        {"name": "A", "price": 1.0, "url": "/a", "image_url": None,
         "original_price": None, "is_sold_out": False}]}
    p2 = {"found": True, "currency": "$", "products": [
        {"name": "B", "price": 2.0, "url": "/b", "image_url": None,
         "original_price": None, "is_sold_out": False}]}
    history = _mk_history([_mk_action_result(p1)], [_mk_action_result(p2)])
    got = _extractions_from_history(history)
    assert [e.products[0].name for e in got] == ["A", "B"]


def test_extractions_from_history_skips_malformed_payloads():
    """A truncated or wrong-shaped payload must not crash the reader — we
    prefer partial results over a failed run (same policy as the old
    _parse_products)."""
    bad = {"found": True, "currency": "", "products": [{"name": None}]}  # name must be str
    history = _mk_history([_mk_action_result(bad)])
    got = _extractions_from_history(history)
    assert got == []


def test_page_task_has_no_persist_step():
    from app.platforms.official_site import _build_page_task
    task = _build_page_task(page_index=1, hint="")
    lower = task.lower()
    assert "write_file" not in lower
    assert "results.jsonl" not in lower
    assert "step 2 — persist" not in lower


def test_page_task_does_not_embed_schema():
    """browser_use already injects the PageResult schema via
    output_model_schema — duplicating it in the prompt adds tokens for
    no signal and is a top contributor to LLM output truncation."""
    from app.platforms.official_site import _build_page_task
    task = _build_page_task(page_index=1, hint="")
    assert '"$defs"' not in task
    assert "Expected output format: PageResult" not in task


def test_page_task_keeps_core_instructions():
    """Don't over-trim: the agent still needs the extract + pagination
    guidance and the infinite-scroll hint propagation."""
    from app.platforms.official_site import _build_page_task
    task = _build_page_task(page_index=2, hint="HINT: scroll down")
    assert "HINT: scroll down" in task
    assert "extract" in task.lower()
    assert "infinite_scroll" in task
    assert "url_param" in task


async def test_extract_page_uses_history_not_file(monkeypatch):
    """Regression guard for Fix A: _extract_page must derive products from
    agent history metadata, not from results.jsonl. A file-free run with a
    non-empty extraction history should still yield products."""
    from app.platforms import official_site as site

    captured_currency = "€"
    extracted = PageExtraction(
        found=True,
        currency=captured_currency,
        products=[
            ProductExtraction(name="X", price=9.9, url="/p/x",
                              image_url="/i/x.jpg"),
        ],
    )

    class FakeHistory:
        def __init__(self):
            self.history = [SimpleNamespace(
                result=[SimpleNamespace(
                    metadata={"extraction_result": {"data": extracted.model_dump()}}
                )]
            )]
        def final_result(self):
            return PageResult(
                currency=captured_currency,
                pagination=Pagination(mechanism="end"),
            ).model_dump_json()

    class FakeAgent:
        def __init__(self, **kwargs):
            pass
        async def run(self, max_steps):
            return FakeHistory()

    monkeypatch.setattr(site, "Agent", FakeAgent)

    result, products = await site._extract_page(
        browser=None, llm=None, page_index=1,
        previous_pagination=None, cancel_event=asyncio.Event(),
    )
    assert result.pagination.mechanism == "end"
    assert result.currency == captured_currency
    assert len(products) == 1
    assert products[0].name == "X"


async def test_orchestrator_uses_deterministic_path_for_url_param(monkeypatch):
    """After page 1 reports mechanism=url_param, subsequent pages must
    go through _extract_page_deterministic, NOT _extract_page."""
    agent_calls: list[int] = []
    det_calls: list[int] = []

    async def fake_nav(**kwargs):
        return NavResult(found=True)

    async def fake_agent(*, page_index, **kwargs):
        agent_calls.append(page_index)
        return _page(
            "url_param",
            [ProductExtraction(name=f"a{page_index}", price=1.0,
                               url=f"https://ex.com/p{page_index}")],
            url_pattern="?page={n}",
        )

    async def fake_det(*, page_index, **kwargs):
        det_calls.append(page_index)
        mech = "end" if page_index >= 3 else "url_param"
        return _page(
            mech,
            [ProductExtraction(name=f"b{page_index}", price=1.0,
                               url=f"https://ex.com/p{page_index}")],
            url_pattern="?page={n}",
        )

    monkeypatch.setattr(official_site, "_navigate_to_category", fake_nav)
    monkeypatch.setattr(official_site, "_extract_page", fake_agent)
    monkeypatch.setattr(official_site, "_extract_page_deterministic", fake_det)

    await _scrape_category(
        browser=None, llm=None,
        brand_url="https://ex.com", section="womens", category="shirts",
        max_products=100, cancel_event=asyncio.Event(),
    )
    assert agent_calls == [1]
    assert det_calls == [2, 3]


async def test_orchestrator_stays_on_agent_path_for_next_button(monkeypatch):
    """next_button mechanism cannot be handled deterministically, so the
    agent path runs on every page."""
    agent_calls: list[int] = []
    det_calls: list[int] = []

    async def fake_nav(**kwargs):
        return NavResult(found=True)

    async def fake_agent(*, page_index, **kwargs):
        agent_calls.append(page_index)
        mech = "end" if page_index >= 3 else "next_button"
        return _page(
            mech,
            [ProductExtraction(name=f"a{page_index}", price=1.0,
                               url=f"https://ex.com/p{page_index}")],
        )

    async def fake_det(**kwargs):
        det_calls.append(kwargs["page_index"])
        raise AssertionError("deterministic path must not run for next_button")

    monkeypatch.setattr(official_site, "_navigate_to_category", fake_nav)
    monkeypatch.setattr(official_site, "_extract_page", fake_agent)
    monkeypatch.setattr(official_site, "_extract_page_deterministic", fake_det)

    await _scrape_category(
        browser=None, llm=None,
        brand_url="https://ex.com", section="womens", category="shirts",
        max_products=100, cancel_event=asyncio.Event(),
    )
    assert agent_calls == [1, 2, 3]
    assert det_calls == []


async def test_deterministic_extract_builds_next_url_for_url_param(monkeypatch):
    """For url_param, the function must compute the next-page URL from the
    current URL + url_pattern and hand it to session.navigate_to. It must
    NOT spin up an Agent, and must NOT scroll (scrolling is the
    infinite_scroll path's responsibility)."""
    from app.platforms import official_site as site

    nav_calls: list[str] = []
    eval_scripts: list[str] = []

    class FakeSession:
        async def get_current_page_url(self):
            return "https://ex.com/cats?color=red"
        async def navigate_to(self, url, new_tab=False):
            nav_calls.append(url)
        async def get_current_page(self):
            class P:
                async def evaluate(self, script):
                    eval_scripts.append(script)
                    return 0
            return P()

    async def fake_extract(*, browser, llm, **kwargs):
        return PageExtraction(
            found=True, currency="$",
            products=[ProductExtraction(name="z", price=1.0, url="/z")],
        )
    async def fake_sleep(_):
        pass

    monkeypatch.setattr(site, "_invoke_extract_tool", fake_extract)
    monkeypatch.setattr(site.asyncio, "sleep", fake_sleep)

    result, products = await site._extract_page_deterministic(
        browser=FakeSession(), llm=None, page_index=2,
        previous_pagination=Pagination(mechanism="url_param", url_pattern="?page={n}"),
        cancel_event=asyncio.Event(),
    )
    # We expected to land on page 2's URL.
    assert len(nav_calls) == 1 and "page=2" in nav_calls[0]
    # Readiness poll may evaluate JS (link count), but must not scroll.
    assert not any("scrollTo" in s for s in eval_scripts)
    assert result.pagination.mechanism == "url_param"
    assert result.pagination.url_pattern == "?page={n}"
    assert products[0].name == "z"


async def test_deterministic_extract_scrolls_and_waits_for_infinite_scroll(monkeypatch):
    """Infinite scroll must (a) scroll, (b) wait for new content to paint
    before extracting, and (c) NOT propagate url_pattern (which only
    applies to url_param)."""
    from app.platforms import official_site as site

    scroll_calls: list[bool] = []

    class FakeSession:
        async def navigate_to(self, url, new_tab=False):
            raise AssertionError("infinite_scroll must not navigate")
        async def get_current_page(self):
            class P:
                async def evaluate(self, _):
                    scroll_calls.append(True)
                    return "0"
            return P()

    async def fake_extract(*, browser, llm, **kwargs):
        return PageExtraction(
            found=True, currency="$",
            products=[ProductExtraction(name="q", price=1.0, url="/q")],
        )
    sleep_calls: list[float] = []
    async def fake_sleep(s):
        sleep_calls.append(s)

    monkeypatch.setattr(site, "_invoke_extract_tool", fake_extract)
    monkeypatch.setattr(site.asyncio, "sleep", fake_sleep)

    result, products = await site._extract_page_deterministic(
        browser=FakeSession(), llm=None, page_index=3,
        previous_pagination=Pagination(mechanism="infinite_scroll"),
        cancel_event=asyncio.Event(),
    )
    assert len(scroll_calls) >= 1                  # scrolled at least once
    assert sum(sleep_calls) >= 1.0                 # waited for content to paint
    assert result.pagination.mechanism == "infinite_scroll"
    assert result.pagination.url_pattern is None   # url_pattern is url_param-only
    assert products[0].name == "q"


async def test_deterministic_extract_propagates_mechanism_on_zero_products(monkeypatch):
    """A single zero-yield deterministic page must NOT force end-of-pagination.
    The orchestrator's two-strike zero_yield_streak guard is the authoritative
    terminator. Previously this function short-circuited to mechanism='end'
    on any empty extract, which turned one flaky SPA render (skeleton-only
    DOM at extract time) into a full run kill on page 2 of 20."""
    from app.platforms import official_site as site

    class FakeSession:
        async def get_current_page_url(self):
            return "https://ex.com/cats?page=6"
        async def navigate_to(self, url, new_tab=False):
            pass
        async def get_current_page(self):
            class P:
                async def evaluate(self, _):
                    return 0
            return P()

    async def fake_extract(*, browser, llm, **kwargs):
        return PageExtraction(found=True, currency="$", products=[])
    async def fake_sleep(_):
        pass

    monkeypatch.setattr(site, "_invoke_extract_tool", fake_extract)
    monkeypatch.setattr(site.asyncio, "sleep", fake_sleep)

    result, products = await site._extract_page_deterministic(
        browser=FakeSession(), llm=None, page_index=7,
        previous_pagination=Pagination(mechanism="url_param", url_pattern="?page={n}"),
        cancel_event=asyncio.Event(),
    )
    assert products == []
    assert result.pagination.mechanism == "url_param"
    assert result.pagination.url_pattern == "?page={n}"


async def test_orchestrator_breaks_on_consecutive_zero_yield_deterministic(monkeypatch):
    """Deterministic path: now that _extract_page_deterministic propagates
    mechanism forward on empty extracts, the outer loop's 2-strike
    zero_yield_streak guard is what terminates a dead run. Two consecutive
    empty deterministic pages must break the loop; one must not."""
    agent_calls: list[int] = []
    det_calls: list[int] = []

    async def fake_nav(**kwargs):
        return NavResult(found=True)

    async def fake_agent(*, page_index, **kwargs):
        agent_calls.append(page_index)
        return _page(
            "url_param",
            [ProductExtraction(name=f"a{page_index}", price=1.0,
                               url=f"https://ex.com/p{page_index}")],
            url_pattern="?page={n}",
        )

    async def fake_det(*, page_index, **kwargs):
        det_calls.append(page_index)
        # Deterministic path returns zero products on every page but
        # preserves the url_param mechanism — mimics a flaky SPA render.
        return _page("url_param", [], url_pattern="?page={n}")

    monkeypatch.setattr(official_site, "_navigate_to_category", fake_nav)
    monkeypatch.setattr(official_site, "_extract_page", fake_agent)
    monkeypatch.setattr(official_site, "_extract_page_deterministic", fake_det)

    await _scrape_category(
        browser=None, llm=None,
        brand_url="https://ex.com", section="womens", category="shirts",
        max_products=100, cancel_event=asyncio.Event(),
    )
    # Page 1 (agent) yields 1 new. Page 2 det yields 0 (streak=1).
    # Page 3 det yields 0 (streak=2) → break. Crucially, page 2 alone
    # did NOT terminate the run.
    assert agent_calls == [1]
    assert det_calls == [2, 3]


async def test_wait_for_listing_ready_returns_when_count_stable(monkeypatch):
    """Simulate an SPA: skeleton (20 links), then grid paints (80 links),
    then stable. The helper should exit once count holds across
    _NAV_STABLE_POLLS consecutive polls."""
    from app.platforms import official_site as site

    counts = iter([20, 50, 80, 80, 80, 80])

    class FakePage:
        async def evaluate(self, _script):
            return next(counts)

    sleeps: list[float] = []
    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(site.asyncio, "sleep", fake_sleep)

    await site._wait_for_listing_ready(FakePage())
    # Polls: 20 (sleep), 50 (sleep), 80 stable=0 (sleep), 80 stable=1
    # (sleep), 80 stable=2 → return (no trailing sleep). 4 sleeps total.
    assert len(sleeps) == 4


async def test_wait_for_listing_ready_respects_max_wait(monkeypatch):
    """When the link count never stabilises, the helper must bail at
    _NAV_MAX_WAIT rather than looping forever."""
    from app.platforms import official_site as site

    counter = {"n": 0}

    class FakePage:
        async def evaluate(self, _script):
            counter["n"] += 1
            # Strictly growing: never satisfies the stability check.
            return counter["n"] * 10

    sleeps: list[float] = []
    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(site.asyncio, "sleep", fake_sleep)

    await site._wait_for_listing_ready(FakePage())
    # _NAV_MAX_WAIT / _NAV_POLL_INTERVAL = 8.0 / 0.5 = 16 polls.
    assert len(sleeps) == int(site._NAV_MAX_WAIT / site._NAV_POLL_INTERVAL)


class TestAdvanceUrlParam:
    def test_appends_page_param_when_missing(self):
        from app.platforms.official_site import _advance_url_param
        assert _advance_url_param("https://ex.com/cats", "?page={n}", 2) == \
            "https://ex.com/cats?page=2"

    def test_replaces_existing_page_param(self):
        from app.platforms.official_site import _advance_url_param
        got = _advance_url_param("https://ex.com/cats?page=1&x=y", "?page={n}", 3)
        assert "page=3" in got
        assert "x=y" in got
        assert got.count("page=") == 1


async def test_orchestrator_carries_pagination_hint_forward(monkeypatch):
    """Page 1's pagination must be fed into page 2's extractor. Routing
    sends url_param to the deterministic path, so the hint shows up there,
    not on the agent path."""
    seen_hints: list[Pagination | None] = []

    async def fake_nav(**kwargs):
        return NavResult(found=True)

    async def fake_agent(*, page_index, previous_pagination, **kwargs):
        seen_hints.append(previous_pagination)
        return _page("url_param",
                     [ProductExtraction(name="a", price=1.0, url="https://ex.com/a")],
                     url_pattern="?page={n}")

    async def fake_det(*, page_index, previous_pagination, **kwargs):
        seen_hints.append(previous_pagination)
        return _page("end",
                     [ProductExtraction(name="b", price=1.0, url="https://ex.com/b")])

    monkeypatch.setattr(official_site, "_navigate_to_category", fake_nav)
    monkeypatch.setattr(official_site, "_extract_page", fake_agent)
    monkeypatch.setattr(official_site, "_extract_page_deterministic", fake_det)

    await _scrape_category(
        browser=None, llm=None,
        brand_url="https://ex.com", section="womens", category="shirts",
        max_products=100, cancel_event=asyncio.Event(),
    )
    assert seen_hints[0] is None
    assert seen_hints[1] is not None
    assert seen_hints[1].mechanism == "url_param"
    assert seen_hints[1].url_pattern == "?page={n}"


from app.platforms.official_site import _build_direct_nav_task


def test_direct_nav_task_starts_from_given_url():
    task = _build_direct_nav_task("https://www2.hm.com/en_sg/kids.html", "kids", "clothing")
    assert "https://www2.hm.com/en_sg/kids.html" in task


def test_direct_nav_task_short_circuits_when_already_on_target():
    task = _build_direct_nav_task("https://example.com/kids", "kids", "clothing")
    lower = task.lower()
    assert "breadcrumb" in lower
    assert "found=true" in lower
    assert "immediately" in lower


def test_direct_nav_task_forbids_top_nav_and_search():
    task = _build_direct_nav_task("https://example.com", "mens", "shirts")
    lower = task.lower()
    assert "do not open the top navigation" in lower or "do not open the hamburger" in lower
    assert "do not use" in lower and ("search bar" in lower or "search_page" in lower)


def test_direct_nav_task_mentions_section_and_category():
    task = _build_direct_nav_task("https://example.com", "womens", "dresses")
    assert "womens" in task
    assert "dresses" in task


import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.platforms.official_site import _navigate_to_category


def _fake_history():
    """Minimal AgentHistory stand-in: final_result() returns None so
    _navigate_to_category falls through to NavResult(found=False)."""
    return MagicMock(final_result=MagicMock(return_value=None))


def test_navigate_uses_menu_prompt_by_default():
    with patch("app.platforms.official_site._build_nav_task", return_value="MENU") as menu, \
         patch("app.platforms.official_site._build_direct_nav_task", return_value="DIRECT") as direct, \
         patch("app.platforms.official_site.Agent") as agent_cls:
        agent_cls.return_value.run = AsyncMock(return_value=_fake_history())
        cancel = asyncio.Event()
        asyncio.run(_navigate_to_category(
            browser=object(), llm=object(),
            brand_url="https://example.com", section="kids", category="clothing",
            cancel_event=cancel,
        ))
        assert menu.called
        assert not direct.called
        assert agent_cls.call_args.kwargs["task"] == "MENU"


# ---- URL-aware click wrapper (A) ----
from app.platforms.official_site import _wrap_click_with_url_check


class _FakeSession:
    def __init__(self, urls):
        # Pop from the front each call — lets the test script before/after.
        self._urls = list(urls)

    async def get_current_page_url(self):
        return self._urls.pop(0)


def _click_result(memory: str = "Clicked a \"Tops & T-shirts\""):
    # Mimics browser_use's ActionResult shape just enough for the wrapper.
    return SimpleNamespace(extracted_content=memory, metadata=None)


async def test_click_wrapper_annotates_url_change():
    calls = []
    async def fake_click(params, browser_session):
        calls.append(params)
        return _click_result()

    wrapped = _wrap_click_with_url_check(fake_click)
    session = _FakeSession(["https://ex.com/kids.html", "https://ex.com/kids/tops.html"])
    result = await wrapped(object(), session)

    assert "URL: https://ex.com/kids.html → https://ex.com/kids/tops.html" in result.extracted_content
    assert len(calls) == 1


async def test_click_wrapper_annotates_url_unchanged():
    """The canonical failure case from the log: click dispatched, page didn't
    move. The wrapper must flag this explicitly so the LLM can't infer
    success from a same-looking DOM."""
    async def fake_click(params, browser_session):
        return _click_result()

    wrapped = _wrap_click_with_url_check(fake_click)
    session = _FakeSession(["https://ex.com/kids.html", "https://ex.com/kids.html"])
    result = await wrapped(object(), session)

    assert "URL unchanged: https://ex.com/kids.html" in result.extracted_content


async def test_click_wrapper_preserves_error_results():
    """If the underlying click returned an error (no extracted_content),
    don't append URL info — the LLM will retry or bail regardless."""
    async def fake_click(params, browser_session):
        return SimpleNamespace(extracted_content=None, error="element not found")

    wrapped = _wrap_click_with_url_check(fake_click)
    session = _FakeSession(["https://ex.com/a", "https://ex.com/a"])
    result = await wrapped(object(), session)

    assert result.extracted_content is None
    assert result.error == "element not found"


async def test_click_wrapper_survives_url_lookup_failure():
    """get_current_page_url can raise if the CDP session is mid-reconnect.
    The wrapper must not crash the click — degrades to unannotated success."""
    async def fake_click(params, browser_session):
        return _click_result("Clicked button")

    class BrokenSession:
        async def get_current_page_url(self):
            raise RuntimeError("CDP disconnected")

    wrapped = _wrap_click_with_url_check(fake_click)
    result = await wrapped(object(), BrokenSession())

    assert result.extracted_content == "Clicked button"  # unchanged, no crash


# ---- NavResult landed_url cross-check (C) ----
def test_nav_result_accepts_landed_url():
    from app.platforms.official_site import NavResult
    nr = NavResult(found=True, landed_url="https://ex.com/kids/tops")
    assert nr.landed_url == "https://ex.com/kids/tops"


def test_nav_result_landed_url_defaults_empty():
    from app.platforms.official_site import NavResult
    nr = NavResult(found=False)
    assert nr.landed_url == ""


def test_navigate_downgrades_found_when_landed_url_mismatches_browser():
    """If the agent reports found=true with a landed_url that doesn't match
    the browser's actual URL, treat it as not found — catches LLM
    confabulation about its location."""
    class FakeBrowser:
        async def get_current_page_url(self):
            return "https://ex.com/kids.html"  # still on the hub, not the subcategory

    # Agent claims it landed on the tops subcategory — but the browser is
    # still on the hub page.
    history = MagicMock(final_result=MagicMock(return_value=NavResult(
        found=True, landed_url="https://ex.com/kids/tops.html",
    ).model_dump_json()))

    with patch("app.platforms.official_site._build_nav_task", return_value="x"), \
         patch("app.platforms.official_site.Agent") as agent_cls:
        agent_cls.return_value.run = AsyncMock(return_value=history)
        result = asyncio.run(_navigate_to_category(
            browser=FakeBrowser(), llm=object(),
            brand_url="https://ex.com", section="kids", category="tops",
            cancel_event=asyncio.Event(),
        ))
    assert result.found is False
    assert result.landed_url == "https://ex.com/kids.html"


def test_navigate_preserves_found_when_landed_url_matches_browser():
    class FakeBrowser:
        async def get_current_page_url(self):
            return "https://ex.com/kids/tops.html"

    history = MagicMock(final_result=MagicMock(return_value=NavResult(
        found=True, landed_url="https://ex.com/kids/tops.html",
    ).model_dump_json()))

    with patch("app.platforms.official_site._build_nav_task", return_value="x"), \
         patch("app.platforms.official_site.Agent") as agent_cls:
        agent_cls.return_value.run = AsyncMock(return_value=history)
        result = asyncio.run(_navigate_to_category(
            browser=FakeBrowser(), llm=object(),
            brand_url="https://ex.com", section="kids", category="tops",
            cancel_event=asyncio.Event(),
        ))
    assert result.found is True


def test_navigate_uses_direct_prompt_when_skip_menu_navigation():
    with patch("app.platforms.official_site._build_nav_task", return_value="MENU") as menu, \
         patch("app.platforms.official_site._build_direct_nav_task", return_value="DIRECT") as direct, \
         patch("app.platforms.official_site.Agent") as agent_cls:
        agent_cls.return_value.run = AsyncMock(return_value=_fake_history())
        cancel = asyncio.Event()
        asyncio.run(_navigate_to_category(
            browser=object(), llm=object(),
            brand_url="https://example.com/kids.html", section="kids", category="clothing",
            cancel_event=cancel,
            skip_menu_navigation=True,
        ))
        assert direct.called
        assert not menu.called
        assert agent_cls.call_args.kwargs["task"] == "DIRECT"


# -----------------------------------------------------------------------------
# _invoke_extract_tool retry behavior
# -----------------------------------------------------------------------------

from app.platforms import _browser_use
from app.platforms._browser_use import _EXTRACT_RETRY_ATTEMPTS
from app.platforms.official_site import _invoke_extract_tool


class _StubRegistry:
    """Mimics `Tools.registry` with a scripted `execute_action`. Each entry
    in `script` is either an Exception (raised) or a result (returned)."""
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
    async def execute_action(self, *_args, **_kwargs):
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _ok_result(products):
    return SimpleNamespace(metadata={
        "extraction_result": {
            "data": {
                "found": True,
                "currency": "$",
                "products": [p.model_dump() for p in products],
            }
        }
    })


async def test_invoke_extract_tool_retries_on_transient_cdp_failure(monkeypatch):
    """Simulates the H&M failure mode: the first `extract` call raises a
    CDP frame-not-found error (modeled as RuntimeError since that's what
    cdp_use raises), the second succeeds. Caller must see the successful
    payload, not an empty PageExtraction."""
    products = [ProductExtraction(name="shirt", price=9.9, url="/shirt")]
    registry = _StubRegistry([
        RuntimeError({"code": -32602, "message": "Frame not found"}),
        _ok_result(products),
    ])
    monkeypatch.setattr(
        _browser_use, "_get_tools",
        lambda: SimpleNamespace(registry=registry),
    )
    sleeps: list[float] = []
    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(_browser_use.asyncio, "sleep", fake_sleep)

    result = await _invoke_extract_tool(browser=object(), llm=object(), query="q")

    assert registry.calls == 2
    assert len(sleeps) == 1            # slept once between attempts
    assert result.found is True
    assert result.products[0].name == "shirt"


async def test_invoke_extract_tool_gives_up_after_max_attempts(monkeypatch):
    """When every attempt raises, caller gets an empty PageExtraction
    (zero-yield page) instead of an exception propagating up."""
    registry = _StubRegistry([RuntimeError("boom")] * _EXTRACT_RETRY_ATTEMPTS)
    monkeypatch.setattr(
        _browser_use, "_get_tools",
        lambda: SimpleNamespace(registry=registry),
    )
    async def fake_sleep(_):
        pass
    monkeypatch.setattr(_browser_use.asyncio, "sleep", fake_sleep)

    result = await _invoke_extract_tool(browser=object(), llm=object(), query="q")

    assert registry.calls == _EXTRACT_RETRY_ATTEMPTS
    assert result.found is False
    assert result.products == []


async def test_invoke_extract_tool_succeeds_first_try(monkeypatch):
    """Happy path: no retry when the first call succeeds."""
    products = [ProductExtraction(name="cap", price=5.0, url="/cap")]
    registry = _StubRegistry([_ok_result(products)])
    monkeypatch.setattr(
        _browser_use, "_get_tools",
        lambda: SimpleNamespace(registry=registry),
    )
    sleeps: list[float] = []
    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(_browser_use.asyncio, "sleep", fake_sleep)

    result = await _invoke_extract_tool(browser=object(), llm=object(), query="q")

    assert registry.calls == 1
    assert sleeps == []
    assert result.products[0].name == "cap"
