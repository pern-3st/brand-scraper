from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator, Protocol, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.models import EnrichmentRequest, EnrichmentRow, FieldDef


@dataclass
class ScrapeContext:
    """Runtime handles passed from the runner into a platform scraper."""
    cancel_event: asyncio.Event
    login_event: asyncio.Event  # set by /scrape/{id}/login_complete
    queue: asyncio.Queue         # SSE event queue


@runtime_checkable
class PlatformScraper(Protocol):
    """Each platform implements this protocol.

    - `sse_event_name`: event name to emit for each yielded record, e.g. "product".
    - `brand_slug(request)`: derive a filesystem-safe slug used in the output path.
    - `stream_products(request, ctx)`: async generator yielding Pydantic models.
    """

    sse_event_name: str
    platform_key: str  # used in storage path: data/scrapes/{platform_key}/{brand}/...

    def brand_slug(self, request: BaseModel) -> str: ...

    def stream_products(
        self,
        request: BaseModel,
        ctx: ScrapeContext,
    ) -> AsyncIterator[BaseModel]: ...


@runtime_checkable
class ProductIdentity(Protocol):
    """Derives a stable join key from a platform's records.

    Returning ``None`` means the record lacks a stable key; the enrichment
    runner skips the record and counts it in ``products_skipped_no_key``.
    """

    def product_key(self, record: BaseModel) -> str | None: ...


@runtime_checkable
class EnrichmentExtractor(Protocol):
    """Platform-side detail-pass extractor. Implementations land in Phase 2/3."""

    platform_key: str
    available_fields: list["FieldDef"]
    supports_freeform: bool

    def stream_enrichments(
        self,
        records: list[BaseModel],
        requested: "EnrichmentRequest",
        ctx: ScrapeContext,
    ) -> AsyncIterator["EnrichmentRow"]: ...
