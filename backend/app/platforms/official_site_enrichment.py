"""Enrichment extractor for retail brand websites.

Uses browser_use + LLM to fill curated + freeform fields from a product
detail page, one structured-extract call per product. No Agent loop — the
scraper already knows the URL; we just need the page's data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, create_model

from app.models import (
    EnrichmentRequest,
    EnrichmentRow,
    FieldDef,
    FieldType,
    FreeformPrompt,
)
from app.platforms._browser_use import build_llm, canonical_url
from app.platforms.base import ScrapeContext
from app.platforms.official_site._session import launch_persistent_context
from app.platforms.official_site.extract_with_llm import extract_structured_from_page

logger = logging.getLogger(__name__)


# Pacing / jitter — Akamai mitigation. Reduces the chance of a mid-run
# block by spacing requests irregularly. Long pause every Nth product
# simulates a human breaking off to think.
_PACE_MIN_SECONDS = 8.0
_PACE_MAX_SECONDS = 20.0
_LONG_PAUSE_EVERY_N = 25
_LONG_PAUSE_MIN_SECONDS = 30.0
_LONG_PAUSE_MAX_SECONDS = 90.0

# After each per-product goto we sleep a short randomised window before
# reading page.content(). DOMContentLoaded fires before SPA hydration
# completes; without this the LLM extracts from a half-rendered shell
# and returns nulls.
_POST_GOTO_SETTLE_MIN_SECONDS = 2.5
_POST_GOTO_SETTLE_MAX_SECONDS = 4.0

# After homepage warmup nav we idle to let Akamai's bmak post a few
# telemetry beats. 3-6s covers bmak's first POST (within ~1s of
# DOMContentLoaded) plus the second batched ping.
_WARMUP_IDLE_MIN_SECONDS = 3.0
_WARMUP_IDLE_MAX_SECONDS = 6.0

# Case-sensitive Akamai/EdgeSuite block-page markers. Akamai's deny page
# always renders these literal strings; localised retail sites preserve
# them because they're injected by EdgeSuite, not the origin app.
_BLOCK_MARKERS = ("Access Denied", "edgesuite.net", "Reference #")

# Matches locale path segments like ``en_sg``, ``en-gb``, ``de``, ``fr_fr``.
# Two letters, optional underscore/hyphen + two letters. Case-insensitive.
_LOCALE_RE = re.compile(r"^[a-z]{2}([_-][a-z]{2})?$", re.IGNORECASE)


async def _pace_sleep(seconds: float, cancel_event: asyncio.Event) -> bool:
    """Sleep for ``seconds``, returning early if ``cancel_event`` fires.

    Returns True if cut short by cancellation, False if the full duration
    elapsed. Callers MUST check the return value and bail when True —
    otherwise long pauses become uncancellable.
    """
    try:
        await asyncio.wait_for(cancel_event.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False


async def _warmup_idle(page: Any, cancel_event: asyncio.Event) -> bool:
    """Sleep ``random(3, 6)`` after the warmup nav. Cancel-aware. Returns
    True if cut short by cancellation."""
    delay = random.uniform(_WARMUP_IDLE_MIN_SECONDS, _WARMUP_IDLE_MAX_SECONDS)
    return await _pace_sleep(delay, cancel_event)


async def _looks_like_block(page: Any) -> bool:
    """Probe the loaded page for Akamai's deny-page signature. Returns False
    on probe error — we do NOT want to abort a pass on a transient evaluate
    glitch (e.g. a frame detached during read)."""
    try:
        snippet = await page.evaluate(
            "document.title + '\\n' + (document.body ? document.body.innerText.slice(0, 2000) : '')"
        )
    except Exception:
        return False
    if not isinstance(snippet, str):
        return False
    return any(m in snippet for m in _BLOCK_MARKERS)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class OfficialSiteProductIdentity:
    """Derives a stable key from ``record.product_url`` (or ``record["product_url"]``).

    Duck-typed to accept both dict (read path — parent run payload is raw JSON)
    and ``ProductRecord`` (write path — runner validates records via
    ``_record_adapter`` before handing to the extractor).
    """

    def product_key(self, record: Any) -> str | None:
        if isinstance(record, dict):
            url = record.get("product_url")
        else:
            url = getattr(record, "product_url", None)
        key = canonical_url(url)
        return key or None


# ---------------------------------------------------------------------------
# Dynamic schema builder
# ---------------------------------------------------------------------------

_PY_TYPE: dict[FieldType, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list[str]": list[str],
}


def build_schema_model(
    *,
    curated: list[FieldDef],
    freeform: list[FreeformPrompt],
    model_name: str = "EnrichmentPayload",
) -> type[BaseModel]:
    """Compile a Pydantic model whose fields match the requested enrichment
    catalog, for use as the ``extraction_schema`` of a browser_use extract call.

    - Curated fields get their declared Python type (``None``-able so the LLM
      can decline).
    - Freeform prompts are all ``str | None`` (the prompt text becomes the
      field description; whatever the model writes is the answer).
    - Every field description is populated — browser_use forwards these into
      the LLM prompt so the model knows what to look for.
    """
    if not curated and not freeform:
        raise ValueError("build_schema_model requires at least one field or prompt")
    fields: dict[str, Any] = {}
    seen: set[str] = set()
    for fd in curated:
        if fd.id in seen:
            raise ValueError(f"duplicate curated field id {fd.id!r}")
        seen.add(fd.id)
        py = _PY_TYPE[fd.type] | None  # type: ignore[operator]
        fields[fd.id] = (py, Field(default=None, description=fd.description or fd.label or fd.id))
    for fp in freeform:
        if fp.id in seen:
            raise ValueError(f"freeform id {fp.id!r} collides with a curated field")
        seen.add(fp.id)
        fields[fp.id] = (
            str | None,
            Field(default=None, description=fp.prompt or fp.label or fp.id),
        )
    return create_model(model_name, __base__=BaseModel, **fields)


# ---------------------------------------------------------------------------
# Curated catalog (v1 seed)
# ---------------------------------------------------------------------------

AVAILABLE_FIELDS: list[FieldDef] = [
    FieldDef(
        id="description",
        label="Description",
        type="str",
        description="Full product description as written on the detail page. Prefer the primary marketing copy over short summaries.",
        category="content",
    ),
    FieldDef(
        id="rating",
        label="Rating",
        type="float",
        description="Average customer rating as a number (e.g. 4.6 out of 5). Return only the numeric value, not the denominator.",
        category="social_proof",
    ),
    FieldDef(
        id="rating_count",
        label="Rating count",
        type="int",
        description="Total number of customer reviews or ratings displayed on the page.",
        category="social_proof",
    ),
    FieldDef(
        id="variants",
        label="Variants",
        type="list[str]",
        description="Available size, colour, or style options shown on the product detail page, as a flat list of labels.",
        category="variants",
    ),
]


# ---------------------------------------------------------------------------
# Extraction query builder
# ---------------------------------------------------------------------------


def build_extraction_query(
    request: EnrichmentRequest,
    *,
    catalog: dict[str, FieldDef] | None = None,
) -> str:
    """Instruction passed to browser_use's ``extract`` tool.

    Browser_use also dumps the JSON Schema (with the same descriptions) into
    ``<output_schema>``, but the LLM follows natural-language guidance in the
    query much more reliably than per-field hints buried in a serialized
    schema. So we restate every requested field's guidance inline here.
    """
    catalog = catalog or {}
    lines: list[str] = [
        "You are on a single product's detail page. Read the visible content "
        "and populate the extraction schema. If a field is not present on the "
        "page, leave it null — do not guess.",
    ]

    if request.curated_fields:
        lines.append("")
        lines.append("Curated fields to extract:")
        for fid in request.curated_fields:
            fd = catalog.get(fid)
            if fd is None:
                lines.append(f"- {fid}")
                continue
            label = fd.label or fid
            desc = fd.description.strip() if fd.description else ""
            lines.append(f"- {fid} ({label}): {desc}" if desc else f"- {fid} ({label})")

    if request.freeform_prompts:
        lines.append("")
        lines.append(
            "Freeform questions — answer each as a short string in the named field:"
        )
        for fp in request.freeform_prompts:
            label = fp.label or fp.id
            prompt = (fp.prompt or "").strip()
            lines.append(f"- {fp.id} ({label}): {prompt}" if prompt else f"- {fp.id} ({label})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class OfficialSiteEnrichment:
    platform_key = "official_site"
    available_fields = AVAILABLE_FIELDS
    supports_freeform = True

    async def stream_enrichments(
        self,
        records: list[BaseModel],
        requested: EnrichmentRequest,
        ctx: ScrapeContext,
    ) -> AsyncIterator[EnrichmentRow]:
        catalog = {fd.id: fd for fd in self.available_fields}
        curated = [catalog[fid] for fid in requested.curated_fields if fid in catalog]
        schema = build_schema_model(curated=curated, freeform=requested.freeform_prompts)
        query = build_extraction_query(requested, catalog=catalog)
        identity = OfficialSiteProductIdentity()

        # Pre-count candidates (records with a stable key) so per-product logs
        # can show "[i/N]" progress against the actual workload, not the raw
        # input length which may include records the identity skips.
        total_candidates = sum(1 for r in records if identity.product_key(r) is not None)
        expected_fields = [fd.id for fd in curated] + [fp.id for fp in requested.freeform_prompts]
        logger.info(
            "official_site enrichment starting: %d products, fields=%s",
            total_candidates, expected_fields,
        )

        llm = build_llm()
        async with launch_persistent_context() as (_p, context):
            page = await context.new_page()

            # Akamai mitigation: warm the session up by visiting the brand
            # homepage first. Without this every per-product nav is a cold
            # tab → product-URL hit, which Akamai scores as bot-shaped.
            warmup_url: str | None = None
            for r in records:
                if identity.product_key(r) is None:
                    continue
                warmup_url = _derive_warmup_url(_product_url(r))
                if warmup_url:
                    break
            if warmup_url:
                logger.info("warmup: navigating to %s", warmup_url)
                try:
                    await page.goto(warmup_url, wait_until="domcontentloaded", timeout=30_000)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("warmup navigation to %s failed: %s", warmup_url, exc)
                else:
                    # Probe before idling — if the homepage itself is denied,
                    # no per-product nav will succeed. Bail without yielding.
                    if await _looks_like_block(page):
                        logger.error(
                            "Akamai block on warmup at %s — aborting pass", warmup_url,
                        )
                        ctx.queue.put_nowait({
                            "event": "log",
                            "data": json.dumps({
                                "message": (
                                    f"Akamai block detected at {warmup_url} (warmup) — "
                                    "aborting enrichment pass."
                                ),
                                "level": "error",
                            }),
                        })
                        return
                    # Real mousewheel scroll — bmak weights mouse/scroll
                    # events heavily. A single wheel tick is enough.
                    try:
                        await page.mouse.wheel(0, random.randint(400, 900))
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("warmup scroll failed (non-fatal): %s", exc)
                    logger.info("warmup: idling before first product")
                    if await _warmup_idle(page, ctx.cancel_event):
                        return

            processed = 0
            for record in records:
                if ctx.cancel_event.is_set():
                    return
                pk = identity.product_key(record)
                if pk is None:
                    # Skipped; caller counts it in products_skipped_no_key.
                    continue

                if processed > 0:
                    if processed % _LONG_PAUSE_EVERY_N == 0:
                        delay = random.uniform(_LONG_PAUSE_MIN_SECONDS, _LONG_PAUSE_MAX_SECONDS)
                        logger.info("long pause %.1fs before next product", delay)
                    else:
                        delay = random.uniform(_PACE_MIN_SECONDS, _PACE_MAX_SECONDS)
                        logger.info("pacing %.1fs before next product", delay)
                    if await _pace_sleep(delay, ctx.cancel_event):
                        return
                processed += 1

                url = _product_url(record)
                values: dict[str, Any] = {}
                errors: dict[str, str] = {}
                logger.info("[%d/%d] navigating to %s", processed, total_candidates, url or "<no url>")
                try:
                    if not url:
                        raise ValueError("record has no product_url")
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    if await _looks_like_block(page):
                        logger.error(
                            "Akamai block detected at %s — aborting pass", url,
                        )
                        ctx.queue.put_nowait({
                            "event": "log",
                            "data": json.dumps({
                                "message": f"Akamai block detected at {url} — aborting enrichment pass.",
                                "level": "error",
                            }),
                        })
                        yield EnrichmentRow(
                            product_key=pk,
                            values={},
                            errors={"_all": "akamai_block"},
                            enriched_at=datetime.now(timezone.utc),
                        )
                        return
                    # Hydration settle. Without this the LLM reads the
                    # pre-hydrated SPA shell and returns nulls. Cancel-aware.
                    if await _pace_sleep(
                        random.uniform(
                            _POST_GOTO_SETTLE_MIN_SECONDS,
                            _POST_GOTO_SETTLE_MAX_SECONDS,
                        ),
                        ctx.cancel_event,
                    ):
                        return
                    result = await extract_structured_from_page(
                        page, llm=llm, schema=schema, query=query,
                    )
                    if result is None:
                        errors["_all"] = "extract returned no data"
                    else:
                        values = result.model_dump(mode="json")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("enrichment failed for %s: %s", pk, exc)
                    errors["_all"] = f"{type(exc).__name__}: {exc}"

                if errors.get("_all"):
                    logger.warning(
                        "[%d/%d] %s — failed: %s",
                        processed, total_candidates, pk, errors["_all"],
                    )
                else:
                    summary = _summarise_values(values, expected_fields)
                    logger.info("[%d/%d] %s — %s", processed, total_candidates, pk, summary)
                yield EnrichmentRow(
                    product_key=pk,
                    values=values,
                    errors=errors,
                    enriched_at=datetime.now(timezone.utc),
                )


def _product_url(record: Any) -> str | None:
    if isinstance(record, dict):
        return record.get("product_url")
    return getattr(record, "product_url", None)


def _summarise_values(values: dict[str, Any], expected_fields: list[str]) -> str:
    """Render extracted values for the per-product log line.

    Truncates long strings so the LogFeed stays readable; lists render with
    their full element count and each element clipped. Missing fields are
    rendered as ``=null``.
    """
    parts: list[str] = []
    for fid in expected_fields:
        if fid in values:
            parts.append(f"{fid}={_fmt_value(values[fid])}")
        else:
            parts.append(f"{fid}=null")
    return ", ".join(parts) if parts else "(no fields)"


def _fmt_value(v: Any, *, str_limit: int = 120, list_limit: int = 8) -> str:
    if v is None:
        return "null"
    if isinstance(v, str):
        s = v.strip().replace("\n", " ")
        return repr(s if len(s) <= str_limit else s[:str_limit] + "…")
    if isinstance(v, list):
        head = [_fmt_value(x, str_limit=40, list_limit=list_limit) for x in v[:list_limit]]
        if len(v) > list_limit:
            head.append(f"…+{len(v) - list_limit}")
        return "[" + ", ".join(head) + "]"
    return repr(v)


def _derive_warmup_url(product_url: str | None) -> str | None:
    """Build a homepage URL to visit before the first product.

    Returns ``scheme://host/{locale}/`` if the first path segment looks like
    a locale; ``scheme://host/`` otherwise. ``None`` if the input can't be
    parsed.
    """
    if not product_url:
        return None
    parts = urlsplit(product_url)
    if not parts.scheme or not parts.netloc:
        return None
    segs = [s for s in parts.path.split("/") if s]
    if segs and _LOCALE_RE.match(segs[0]):
        path = f"/{segs[0]}/"
    else:
        path = "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
