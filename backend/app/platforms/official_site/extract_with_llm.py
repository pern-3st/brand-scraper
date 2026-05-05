"""LLM-based structured extraction from a patchright Page.

Replaces the browser_use ``Tools.extract`` action for the official-site
enrichment path. We need this because browser_use's extract is hardwired
to its own ``BrowserSession`` (which uses vanilla Playwright); migrating
to patchright means dropping that dep on the page-acquisition side. The
LLM call itself still uses ``SanitizedChatOpenAI`` from ``_browser_use``,
which keeps the per-call fallback and tab-cap defenses.

Prompt template mirrors browser_use's structured-extract path verbatim
(``browser_use/tools/service.py:1052-1078``). The wording carries the
"do not guess, return null when missing" discipline that the LLM has
been observed to follow reliably; rewriting it regresses extraction
quality.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from browser_use.llm.messages import SystemMessage, UserMessage
from bs4 import BeautifulSoup
from markdownify import markdownify
from pydantic import BaseModel

from app.platforms._browser_use import _cap_tab_runs

logger = logging.getLogger(__name__)


# Matches browser_use's MAX_CHAR_LIMIT (service.py:964). A product detail
# page virtually never exceeds 100k chars of post-strip markdown; if it
# does, head-truncation is fine — extraction targets are above the fold.
_MAX_CHAR_LIMIT = 100_000

# Tags we always strip — pure noise for extraction.
_STRIP_TAGS = ["script", "style", "noscript", "iframe", "svg"]

# Per-call LLM budget. Matches browser_use's structured-extract timeout.
_EXTRACT_TIMEOUT_SECONDS = 120.0


_SYSTEM_PROMPT = """
You are an expert at extracting structured data from the markdown of a webpage.

<input>
You will be given a query, a JSON Schema, and the markdown of a webpage that has been filtered to remove noise and advertising content.
</input>

<instructions>
- Extract ONLY information present in the webpage. Do not guess or fabricate values.
- Your response MUST conform to the provided JSON Schema exactly.
- If a required field's value cannot be found on the page, use null (if the schema allows it) or an empty string / empty array as appropriate.
- If the content was truncated, extract what is available from the visible portion.
</instructions>
""".strip()


def html_to_markdown(html: str) -> str:
    """HTML → markdown with noise tags + their content removed, tab-runs
    capped, and size-bounded.

    markdownify's ``strip`` only drops tag wrappers (text inside survives)
    so we pre-strip noise nodes via BeautifulSoup before conversion.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    md = markdownify(str(soup))
    # Strip lone surrogate codepoints — they crash UTF-8 round-trips downstream.
    md = md.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    md = _cap_tab_runs(md)
    if len(md) > _MAX_CHAR_LIMIT:
        md = md[:_MAX_CHAR_LIMIT]
    return md


async def extract_structured_from_page(
    page: Any,
    *,
    llm: Any,
    schema: type[BaseModel],
    query: str,
) -> BaseModel | None:
    """Pull HTML from ``page``, ask ``llm`` to populate ``schema``, return the
    model. Returns ``None`` on any failure (timeout, LLM error, validation).
    """
    try:
        html = await page.content()
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not read page.content(): %s", exc)
        return None

    md = html_to_markdown(html)

    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    user_prompt = (
        f"<query>\n{query}\n</query>\n\n"
        f"<output_schema>\n{schema_json}\n</output_schema>\n\n"
        f"<webpage_content>\n{md}\n</webpage_content>"
    )

    logger.info("invoking LLM extraction (markdown=%d chars)", len(md))
    try:
        response = await asyncio.wait_for(
            llm.ainvoke(
                [SystemMessage(content=_SYSTEM_PROMPT), UserMessage(content=user_prompt)],
                output_format=schema,
            ),
            timeout=_EXTRACT_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM extraction failed: %s", exc)
        return None

    completion = getattr(response, "completion", None)
    if isinstance(completion, schema):
        return completion
    # Defensive: some clients return a dict instead of the model instance.
    if isinstance(completion, dict):
        try:
            return schema.model_validate(completion)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM returned dict that failed validation: %s", exc)
            return None
    logger.warning("LLM response had no usable completion: %r", completion)
    return None
