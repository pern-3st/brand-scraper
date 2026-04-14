from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable

from pydantic import BaseModel


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
