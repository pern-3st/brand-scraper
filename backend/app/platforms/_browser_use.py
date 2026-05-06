"""Shared browser_use scaffolding.

Lifted from ``official_site.py`` so the grid scraper and the enrichment
extractors can both consume it without duplicating LLM / browser / schema
plumbing.

This module is browser_use-specific. Patchright-based platforms (Shopee)
have their own session helper at ``shopee/_session.py``.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from browser_use import BrowserProfile, BrowserSession, ChatOpenAI
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.messages import BaseMessage
from browser_use.tools.service import Tools
from pydantic import BaseModel, ValidationError

from app import settings

logger = logging.getLogger(__name__)


from app.paths import HIDDEN_BROWSER_PROFILES_DIR

# Embeds the literal ``browser-use-user-data-dir-`` substring so browser_use's
# BrowserProfile._copy_profile (model_post_init) short-circuits and reuses
# the persistent dir instead of cloning it into a fresh tempdir each launch.
OFFICIAL_SITE_PROFILE_DIR: Path = (
    HIDDEN_BROWSER_PROFILES_DIR / "browser-use-user-data-dir-official_site"
)


# ---------------------------------------------------------------------------
# Tab-run sanitiser + per-call-fallback chat client
# ---------------------------------------------------------------------------

# browser_use's DOM serializer uses ``depth * '\t'`` for tree indentation
# (browser_use/dom/serializer/serializer.py), so deeply nested pages feed
# the LLM lines with 20+ consecutive tabs. Models — especially Grok and
# gpt-4.1-mini — fall into a degenerate decoding loop and spam tabs in
# their own output until max_tokens, producing truncated structured-output
# JSON. Capping tab-runs in the input breaks the mirror without losing
# hierarchy for shallow nesting.
_MAX_TAB_RUN = 4
_TAB_RUN_RE = re.compile(r"\t{" + str(_MAX_TAB_RUN + 1) + r",}")
_TAB_CAP = "\t" * _MAX_TAB_RUN


def _cap_tab_runs(text: str) -> str:
    return _TAB_RUN_RE.sub(_TAB_CAP, text)


def _sanitize_message_content(msg: BaseMessage) -> None:
    """Mutate the message in place, capping runs of tabs in every text part."""
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        msg.content = _cap_tab_runs(content)
    elif isinstance(content, list):
        for part in content:
            text = getattr(part, "text", None)
            if isinstance(text, str):
                part.text = _cap_tab_runs(text)


class SanitizedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with two defenses layered on top of the base client:

    1. Collapses long tab-runs in every outgoing message (see
       ``_cap_tab_runs``) to break the decoder-level tab-loop pathology.

    2. Per-call fallback: if ``_fallback`` is attached, any exception from
       the primary retries the SAME call once on the fallback and returns
       its result. Unlike browser_use's Agent-level ``fallback_llm`` —
       which swaps permanently at the first retryable error
       (agent/service.py:2003) — this isolates the swap to the single
       failing call. The next call goes back to the primary, so a brief
       grok-fast hiccup doesn't condemn the rest of the run to the weaker
       model.
    """

    async def ainvoke(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        output_format: Any = None,
        **kwargs: Any,
    ) -> Any:
        for m in messages:
            _sanitize_message_content(m)
        try:
            return await super().ainvoke(messages, output_format=output_format, **kwargs)
        except Exception as exc:
            fallback = getattr(self, "_fallback", None)
            if fallback is None:
                raise
            logger.warning(
                "primary LLM failed for this call (%s: %s); retrying once on fallback",
                type(exc).__name__,
                exc,
            )
            return await fallback.ainvoke(messages, output_format=output_format, **kwargs)


# Sibling model used by ``SanitizedChatOpenAI``'s per-call fallback (NOT
# browser_use's Agent-level fallback — see class docstring). Different
# family from the primary so a model-specific decoder pathology (e.g.
# tab-loops) doesn't take both out at once, and capable enough to actually
# recover the call: ``nano``-tier models were observed to produce
# truncated JSON, hallucinated page state, and ignore negative task
# instructions under pressure, so every fallback invocation made the run
# worse.
FALLBACK_MODEL = "qwen/qwen3.5-27b"


# ---------------------------------------------------------------------------
# URL canonicalisation
# ---------------------------------------------------------------------------


def canonical_url(raw: str | None, *, base: str | None = None) -> str:
    """Return a stable key for deduplication, or ``""`` if the input
    cannot be canonicalised. Strips query + fragment, lowercases the host,
    trims a trailing slash (except at root). Relative URLs are resolved
    against ``base`` when supplied. Callers treat ``""`` as "no dedup
    key, drop the record."
    """
    if raw is None:
        return ""
    raw = raw.strip()
    if not raw:
        return ""
    resolved = urljoin(base, raw) if base else raw
    parts = urlsplit(resolved)
    if not parts.scheme or not parts.netloc:
        return ""
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))


# ---------------------------------------------------------------------------
# Pydantic → browser_use schema compiler
# ---------------------------------------------------------------------------


def _flatten_nullable_any_of(node: dict) -> dict:
    """Pydantic renders ``Optional[X]`` as
    ``{"anyOf": [{"type": X}, {"type": "null"}]}``. browser_use's
    ``schema_dict_to_pydantic_model`` rejects ``anyOf`` outright but
    understands ``{"type": X, "nullable": true}``, so rewrite the common
    Optional pattern into that form."""
    any_of = node.get("anyOf")
    if not isinstance(any_of, list) or len(any_of) != 2:
        return node
    null_branch = next(
        (b for b in any_of if isinstance(b, dict) and b.get("type") == "null"), None
    )
    other_branch = next(
        (b for b in any_of if isinstance(b, dict) and b is not null_branch), None
    )
    if null_branch is None or other_branch is None:
        return node
    merged = {k: v for k, v in node.items() if k != "anyOf"}
    for k, v in other_branch.items():
        merged.setdefault(k, v)
    merged["nullable"] = True
    return merged


def _compile_extraction_schema(schema: dict) -> dict:
    """Transform a Pydantic-emitted JSON Schema into the subset accepted
    by browser_use's extraction-schema validator.

    - Inlines ``$ref``/``$defs`` (browser_use rejects both).
    - Rewrites ``Optional[X]`` ``anyOf`` pairs as
      ``{type: X, nullable: true}``.

    Leaves the input untouched (returns a new dict).
    """
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].rsplit("/", 1)[-1]
                return walk(defs[ref_name])
            rewritten = {k: walk(v) for k, v in node.items() if k != "$defs"}
            return _flatten_nullable_any_of(rewritten)
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


# ---------------------------------------------------------------------------
# Module-level Tools / FileSystem singletons
# ---------------------------------------------------------------------------

# Module-scoped Tools instance — Tools.__init__ registers every action
# and is not free; we only need one shared registry for direct action
# calls.
_TOOLS: Tools | None = None


def _get_tools() -> Tools:
    global _TOOLS
    if _TOOLS is None:
        _TOOLS = Tools()
    return _TOOLS


# Separate FileSystem for direct extract calls. The ``extract`` action
# writes overflow content here when the extracted string exceeds ~10 KB
# (browser_use/tools/service.py:1107–1114). Passing None crashes on any
# non-trivial listing page — not optional.
_EXTRACT_FS: FileSystem | None = None


def _get_extract_fs() -> FileSystem:
    global _EXTRACT_FS
    if _EXTRACT_FS is None:
        _EXTRACT_FS = FileSystem(Path.cwd())
    return _EXTRACT_FS


# ---------------------------------------------------------------------------
# Generalised structured extraction
# ---------------------------------------------------------------------------

# Retry budget for ``extract_structured``. browser_use's ``extract``
# internally builds a full DOM+AX tree via ``_get_ax_tree_for_all_frames``,
# which uses a plain ``asyncio.gather`` — one transient frame detach
# (ads/analytics iframe reshuffling during hydration) aborts the whole
# snapshot with a CDP -32602 "Frame with the given frameId is not found".
# These races almost always settle within a second, so one retry after a
# short sleep recovers the page without punishing the run on genuine
# extract failures.
_EXTRACT_RETRY_ATTEMPTS = 2
_EXTRACT_RETRY_DELAY = 0.8


async def extract_structured(
    *,
    browser: BrowserSession,
    llm: ChatOpenAI,
    schema: type[BaseModel],
    query: str,
    extract_links: bool = True,
    extract_images: bool = True,
) -> BaseModel | None:
    """One-shot structured extraction against the current page. Retries
    once on transient frame-detach (CDP -32602). Returns None on hard
    failure.

    The returned model is the ``schema`` type the caller passed in.
    """
    compiled = _compile_extraction_schema(schema.model_json_schema())
    result: Any = None
    for attempt in range(1, _EXTRACT_RETRY_ATTEMPTS + 1):
        try:
            result = await _get_tools().registry.execute_action(
                "extract",
                {
                    "query": query,
                    "extract_links": extract_links,
                    "extract_images": extract_images,
                },
                browser_session=browser,
                page_extraction_llm=llm,
                file_system=_get_extract_fs(),
                extraction_schema=compiled,
            )
            break
        except Exception as exc:  # noqa: BLE001
            if attempt < _EXTRACT_RETRY_ATTEMPTS:
                logger.warning(
                    "extract_structured failed (attempt %d/%d): %s — retrying",
                    attempt, _EXTRACT_RETRY_ATTEMPTS, exc,
                )
                await asyncio.sleep(_EXTRACT_RETRY_DELAY)
            else:
                logger.warning(
                    "extract_structured failed (attempt %d/%d): %s",
                    attempt, _EXTRACT_RETRY_ATTEMPTS, exc,
                )
                return None

    meta = getattr(result, "metadata", None)
    if not isinstance(meta, dict):
        return None
    extraction = meta.get("extraction_result")
    if not isinstance(extraction, dict):
        return None
    data = extraction.get("data")
    if not isinstance(data, dict):
        return None
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        logger.warning("extract_structured payload failed validation: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def build_llm() -> SanitizedChatOpenAI:
    """Build the primary ChatOpenAI client wired against OpenRouter, with
    the per-call fallback attached.

    Reads ``openrouter_api_key`` and ``openrouter_model`` from
    ``app.settings``. Raises if the key is missing.
    """
    effective = settings.load()
    api_key = effective["openrouter_api_key"]
    model = effective["openrouter_model"]
    if not api_key:
        raise RuntimeError(
            "OpenRouter API key is not configured. Open the dashboard settings "
            "(gear icon) and paste your key, or set OPENROUTER_API_KEY in the "
            "environment."
        )
    # max_completion_tokens 4096 (library default) left no headroom when the
    # model produced long free-text blocks → truncation = EOF JSON.
    # frequency_penalty 0.3 (library default) is too weak — bump as
    # defence-in-depth against any decoder repetition loop.
    llm = SanitizedChatOpenAI(
        model=model,
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        max_completion_tokens=8192,
        frequency_penalty=0.6,
    )
    llm._fallback = ChatOpenAI(
        model=FALLBACK_MODEL,
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        max_completion_tokens=8192,
        frequency_penalty=0.6,
    )
    return llm


def build_browser_profile() -> BrowserProfile:
    """Browser profile tuned for slow / skeleton-heavy retail SPAs.

    Default wait budgets (0.25s / 0.5s / 0.1s) are too aggressive — the
    agent captures DOM state while loaders are still painting, sees a
    near-empty tab-indented tree, and either misclicks or falls into the
    tab-loop.

    A persistent ``user_data_dir`` is mandatory: Akamai-protected sites
    (H&M etc.) score a freshly-minted browser as bot. Reusing the profile
    ages the ``_abck`` cookie across runs and dramatically reduces the
    chance of a mid-run block. Chrome locks the dir, so concurrent runs
    will fail loudly — acceptable for a single-user desktop app.

    The directory name embeds ``browser-use-user-data-dir-`` to bypass
    browser-use's ``_copy_profile`` model_post_init, which would otherwise
    copy our profile into a fresh temp dir each launch (defeating the
    cookie-aging we want). See ``BrowserProfile._copy_profile`` —
    line 808 short-circuits when that substring appears in the path.
    """
    user_data_dir = OFFICIAL_SITE_PROFILE_DIR
    user_data_dir.mkdir(parents=True, exist_ok=True)
    return BrowserProfile(
        headless=False,
        keep_alive=True,
        channel="chrome",
        user_data_dir=str(user_data_dir),
        minimum_wait_page_load_time=4.0,
        wait_for_network_idle_page_load_time=8.0,
        wait_between_actions=0.5,
    )
