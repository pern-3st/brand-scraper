"""Tests for the patchright-side LLM extraction helper."""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.platforms.official_site.extract_with_llm import (
    extract_structured_from_page,
    html_to_markdown,
)


class _Schema(BaseModel):
    description: str | None = None
    rating: float | None = None


class _FakePage:
    def __init__(self, html: str) -> None:
        self._html = html

    async def content(self) -> str:
        return self._html


class _FakeResponse:
    def __init__(self, completion: BaseModel) -> None:
        self.completion = completion


class _FakeLLM:
    """Records the prompt and returns a canned schema-conforming completion."""

    def __init__(self, completion: BaseModel) -> None:
        self.completion = completion
        self.calls: list[dict] = []

    async def ainvoke(self, messages, output_format=None, **kwargs):
        self.calls.append({"messages": messages, "output_format": output_format})
        return _FakeResponse(self.completion)


def test_html_to_markdown_strips_scripts_and_caps_tabs():
    html = (
        "<html><body>"
        "<script>tracker()</script>"
        "<style>.a{}</style>"
        "<noscript>fallback</noscript>"
        "<div>" + "\t" * 20 + "Hello world</div>"
        "</body></html>"
    )
    md = html_to_markdown(html)
    assert "tracker" not in md
    assert ".a{}" not in md
    assert "fallback" not in md
    assert "\t" * 20 not in md  # capped


@pytest.mark.asyncio
async def test_extract_structured_returns_parsed_model():
    page = _FakePage("<html><body><h1>A shoe</h1><p>desc</p></body></html>")
    llm = _FakeLLM(_Schema(description="A shoe — desc", rating=4.5))
    result = await extract_structured_from_page(
        page, llm=llm, schema=_Schema, query="extract description and rating",
    )
    assert isinstance(result, _Schema)
    assert result.description == "A shoe — desc"
    assert result.rating == 4.5
    # The query made it into the user prompt.
    user_msg = llm.calls[0]["messages"][-1]
    assert "extract description and rating" in user_msg.content


@pytest.mark.asyncio
async def test_extract_structured_returns_none_on_llm_error():
    page = _FakePage("<html><body>x</body></html>")

    class _BoomLLM:
        async def ainvoke(self, messages, output_format=None, **kwargs):
            raise RuntimeError("openrouter is down")

    result = await extract_structured_from_page(
        page, llm=_BoomLLM(), schema=_Schema, query="q",
    )
    assert result is None
