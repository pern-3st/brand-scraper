"""Shopee enrichment extractor.

Reuses the existing patchright persistent context from
``shopee/_session.py`` so the one-time interactive login cookie survives
across calls. Fields are pulled via a single ``page.evaluate()`` against
the product-detail DOM (see ``extract_product.py``) — no second browser
stack, no LLM round-trip.

``supports_freeform = False`` in v1: any attempt to request freeform
prompts is rejected at request-validation time in ``main.py``. If a
request still reaches the extractor with freeform prompts (belt &
braces), we emit a ``_all`` error per row rather than silently dropping.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from pydantic import BaseModel

from app.models import (
    EnrichmentRequest,
    EnrichmentRow,
    FieldDef,
)
from app.platforms.base import ScrapeContext
from app.platforms.shopee._session import (
    launch_persistent_context,
    navigate_with_login_wall_recovery,
)
from app.platforms.shopee.extract_product import (
    PRODUCT_READY_SELECTOR,
    extract_product_fields,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class ShopeeProductIdentity:
    """Shopee's stable per-product key is the integer ``item_id``.

    URL slugs change; IDs don't — confirmed during the 2026-04-10 spike.
    Accepts dict (read path — raw JSON) and ``ShopeeProductRecord`` (write path).
    """

    def product_key(self, record: Any) -> str | None:
        if isinstance(record, dict):
            item_id = record.get("item_id")
        else:
            item_id = getattr(record, "item_id", None)
        if item_id is None:
            return None
        try:
            return str(int(item_id))
        except (TypeError, ValueError):
            return None


# ---------------------------------------------------------------------------
# Curated catalog (v1 seed)
# ---------------------------------------------------------------------------

AVAILABLE_FIELDS: list[FieldDef] = [
    FieldDef(
        id="description",
        label="Description",
        type="str",
        description="Long-form product description as rendered in the Product Description section.",
        category="content",
    ),
    FieldDef(
        id="variant_options",
        label="Variant options",
        type="list[str]",
        description="Selectable variation chips (size, colour, style) shown on the product page.",
        category="variants",
    ),
    FieldDef(
        id="shop_name",
        label="Shop name",
        type="str",
        description="Display name of the shop that lists the product.",
        category="shop",
    ),
    FieldDef(
        id="shop_rating",
        label="Shop rating",
        type="float",
        description="Average shop rating as a number between 0 and 5.",
        category="shop",
    ),
    FieldDef(
        id="shop_follower_count",
        label="Shop followers",
        type="int",
        description="Total followers of the shop displayed on the product page.",
        category="shop",
    ),
    FieldDef(
        id="rating_count",
        label="Rating count",
        type="int",
        description="Total number of product ratings shown on the product page.",
        category="social_proof",
    ),
]


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class ShopeeEnrichment:
    platform_key = "shopee"
    available_fields = AVAILABLE_FIELDS
    supports_freeform = False

    async def stream_enrichments(
        self,
        records: list[BaseModel],
        requested: EnrichmentRequest,
        ctx: ScrapeContext,
    ) -> AsyncIterator[EnrichmentRow]:
        if requested.freeform_prompts:
            # Request validation should have caught this; guard anyway so
            # we don't silently behave as if freeform had been honoured.
            raise ValueError("shopee enrichment does not support freeform prompts in v1")

        catalog = {fd.id for fd in self.available_fields}
        requested_ids = [fid for fid in requested.curated_fields if fid in catalog]
        if not requested_ids:
            raise ValueError("shopee enrichment request has no known curated fields")

        identity = ShopeeProductIdentity()

        async with launch_persistent_context() as (_p, context):
            page = await context.new_page()
            for record in records:
                if ctx.cancel_event.is_set():
                    return
                pk = identity.product_key(record)
                if pk is None:
                    continue
                url = _product_url(record)
                values: dict[str, Any] = {}
                errors: dict[str, str] = {}
                try:
                    if not url:
                        raise ValueError("record has no product_url")
                    ready = await navigate_with_login_wall_recovery(
                        page, url, ctx, ready_selector=PRODUCT_READY_SELECTOR,
                    )
                    if not ready:
                        # Cancelled during login wait — stop the whole pass.
                        return
                    extracted = await extract_product_fields(page)
                    for fid in requested_ids:
                        val = extracted.get(fid) if isinstance(extracted, dict) else None
                        if val is None:
                            errors[fid] = "not found on page"
                        else:
                            values[fid] = val
                except Exception as exc:  # noqa: BLE001
                    log.warning("shopee enrichment failed for %s: %s", pk, exc)
                    errors = {"_all": f"{type(exc).__name__}: {exc}"}
                    values = {}
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
