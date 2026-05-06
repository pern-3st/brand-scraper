"""Lazada product identity.

Split out from a (deferred) ``enrichment.py`` because the unified-table
view needs a registered ``ProductIdentity`` even before per-PDP
enrichment lands. When Phase 5 of the Lazada plan ships, the extractor
can live alongside this class or move into a sibling ``enrichment.py``.
"""
from __future__ import annotations

from typing import Any


class LazadaProductIdentity:
    """Stable per-product key is the integer ``item_id`` (auctionId).

    Accepts dict (read path — raw JSON) and ``LazadaProductRecord``
    (write path), matching the Shopee identity's shape.
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
