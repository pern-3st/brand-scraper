"""Enrichment extractor for retail brand websites.

Uses browser_use + LLM to fill curated + freeform fields from a product
detail page, one structured-extract call per product. No Agent loop — the
scraper already knows the URL; we just need the page's data.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from browser_use import BrowserSession
from pydantic import BaseModel, Field, create_model

from app.models import (
    EnrichmentRequest,
    EnrichmentRow,
    FieldDef,
    FieldType,
    FreeformPrompt,
)
from app.platforms._browser_use import (
    build_browser_profile,
    build_llm,
    canonical_url,
    extract_structured,
)
from app.platforms.base import ScrapeContext

logger = logging.getLogger(__name__)


# Pacing / jitter — Akamai mitigation. Reduces the chance of a mid-run
# block by spacing requests irregularly. Long pause every Nth product
# simulates a human breaking off to think.
_PACE_MIN_SECONDS = 8.0
_PACE_MAX_SECONDS = 20.0
_LONG_PAUSE_EVERY_N = 25
_LONG_PAUSE_MIN_SECONDS = 30.0
_LONG_PAUSE_MAX_SECONDS = 90.0


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

        llm = build_llm()
        browser = BrowserSession(browser_profile=build_browser_profile())
        # Agent.run() starts the session internally; this path bypasses Agent,
        # so without an explicit start() the CDP client is never connected and
        # every extract call fails with "CDP client not initialized".
        await browser.start()
        try:
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
                    else:
                        delay = random.uniform(_PACE_MIN_SECONDS, _PACE_MAX_SECONDS)
                    if await _pace_sleep(delay, ctx.cancel_event):
                        return
                processed += 1

                url = _product_url(record)
                values: dict[str, Any] = {}
                errors: dict[str, str] = {}
                try:
                    if not url:
                        raise ValueError("record has no product_url")
                    await browser.navigate_to(url)
                    result = await extract_structured(
                        browser=browser, llm=llm, schema=schema, query=query,
                    )
                    if result is None:
                        errors["_all"] = "extract returned no data"
                    else:
                        values = result.model_dump(mode="json")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("enrichment failed for %s: %s", pk, exc)
                    errors["_all"] = f"{type(exc).__name__}: {exc}"
                yield EnrichmentRow(
                    product_key=pk,
                    values=values,
                    errors=errors,
                    enriched_at=datetime.now(timezone.utc),
                )
        finally:
            await browser.stop()


def _product_url(record: Any) -> str | None:
    if isinstance(record, dict):
        return record.get("product_url")
    return getattr(record, "product_url", None)
