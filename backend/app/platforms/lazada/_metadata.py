"""ID → display-name resolution for the Lazada catalog.

Both names we need (brand + category) are resolvable from two responses
that fire automatically on the shop landing — no per-PDP visits, no
explicit fetches:

  - ``/shop/renderApi/lzdPcPageData`` → SSR payload carrying
    ``result.globalData`` (shopId / sellerId / campaignId / promotionTag)
    and ``result.components`` (a dict of ~80 components, one of which
    holds ``formData.shopName.{en,zh}``). The component id rotates per
    page, so we walk the dict for the entry containing ``shopName``
    rather than indexing positionally.
  - ``mtop.lazada.guided.shopping.categories.categorieslpcommon`` →
    a global category tree we flatten into ``{categoryId: name}``.

For a single-brand "Official store" shop, brand display name equals
``shopName.en`` (verified for Lacoste in the spike). Multi-brand shops
fall back to leaving ``brand_name`` unset.

``MetadataResolver`` registers handlers on the same ``page.on("response")``
channel that the scraper uses for the catalog. ``wait_until_ready()``
blocks the scroll loop until both metadata sources have arrived (with a
timeout — degrades to ID-only enrichment if either is missing).
``enrich(item)`` mutates the item dict in place.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

LZD_PAGE_DATA_FRAGMENT = "/shop/renderApi/lzdPcPageData"
CATEGORIES_TREE_FRAGMENT = "mtop.lazada.guided.shopping.categories.categorieslpcommon"


class MetadataResolver:
    def __init__(self) -> None:
        self.shop_id: int | None = None
        self.seller_id: int | None = None
        self.brand_name: str | None = None
        self.shop_name: str | None = None
        # categoryId (int) → name. Built once on first capture; reused for
        # all items.
        self.category_names: dict[int, str] = {}

        self._page_data_event = asyncio.Event()
        self._categories_event = asyncio.Event()

    def url_matches(self, url: str) -> bool:
        return LZD_PAGE_DATA_FRAGMENT in url or CATEGORIES_TREE_FRAGMENT in url

    def ingest(self, url: str, payload: Any) -> None:
        """Feed a response body in. No-op when ``url`` doesn't match a
        known metadata endpoint or ``payload`` is malformed."""
        if LZD_PAGE_DATA_FRAGMENT in url:
            self._ingest_page_data(payload)
            self._page_data_event.set()
        elif CATEGORIES_TREE_FRAGMENT in url:
            self._ingest_categories(payload)
            self._categories_event.set()

    async def wait_until_ready(self, timeout: float = 15.0) -> bool:
        """Block until both metadata sources have arrived.

        Returns True when both are present, False when either timed out.
        The caller can proceed in either case — missing metadata simply
        means brand_name / category_name will be left unset.
        """
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    self._page_data_event.wait(),
                    self._categories_event.wait(),
                ),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            log.info(
                "lazada: metadata wait timed out after %.1fs "
                "(page_data=%s, categories=%s) — "
                "continuing with whatever resolved so far",
                timeout,
                self._page_data_event.is_set(),
                self._categories_event.is_set(),
            )
            return False

    def enrich(self, item: dict) -> None:
        """Mutate ``item`` in place: fill brand_name and category fields,
        translate the int lineage stashed at ``_category_id_lineage`` into
        a list of names, then drop the lineage key.

        Lineage names are dropped (not present) when the categories tree
        is missing or doesn't cover that id — better to omit than to lie.
        """
        if self.brand_name is not None and item.get("brand_name") is None:
            item["brand_name"] = self.brand_name

        if self.shop_id is not None and item.get("shop_id") is None:
            item["shop_id"] = self.shop_id
        if self.seller_id is not None and item.get("seller_id") is None:
            item["seller_id"] = self.seller_id

        cid = item.get("category_id")
        if isinstance(cid, int):
            name = self.category_names.get(cid)
            if name:
                item["category_name"] = name

        lineage_ids = item.pop("_category_id_lineage", None)
        if isinstance(lineage_ids, list) and self.category_names:
            names = [self.category_names[i] for i in lineage_ids if i in self.category_names]
            if names:
                item["category_lineage"] = names

    # --- internal --------------------------------------------------------

    def _ingest_page_data(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        result = payload.get("result")
        if not isinstance(result, dict):
            return
        gd = result.get("globalData")
        if isinstance(gd, dict):
            shop_id = gd.get("shopId")
            seller_id = gd.get("sellerId")
            if isinstance(shop_id, int):
                self.shop_id = shop_id
            if isinstance(seller_id, int):
                self.seller_id = seller_id

        components = result.get("components")
        if isinstance(components, dict):
            shop_name = _find_shop_name(components)
            if shop_name is not None:
                self.shop_name = shop_name
                # For single-brand "Official store" shops the brand display
                # name equals shopName.en — verified for Lacoste in the
                # spike. Multi-brand shops are out of scope for MVP, so
                # using shopName as brand_name is acceptable (callers can
                # later choose to clear it for known multi-brand handles).
                self.brand_name = shop_name

    def _ingest_categories(self, payload: Any) -> None:
        """Flatten ``categoriesLpMultiFloor.data`` into ``{id: name}``.

        Walks all three levels (level1 / level2TabList / level3TabList).
        The id-space is sparser than the ``categoryId``s actually used in
        per-item payloads; a miss is normal and just means the item's
        category isn't in the global tree.
        """
        if not isinstance(payload, dict):
            return
        rv = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(rv, dict):
            return
        rv = rv.get("resultValue") if isinstance(rv.get("resultValue"), dict) else rv
        if not isinstance(rv, dict):
            return
        floors = rv.get("categoriesLpMultiFloor")
        if not isinstance(floors, dict):
            return
        items = floors.get("data")
        if not isinstance(items, list):
            return
        out: dict[int, str] = {}
        for l1 in items:
            if not isinstance(l1, dict):
                continue
            l1_name = l1.get("categoryName")
            l1_id = _coerce_int(l1.get("id") or l1.get("level1CategoryId"))
            if l1_id is not None and isinstance(l1_name, str):
                out[l1_id] = l1_name
            for l2 in l1.get("level2TabList") or []:
                if not isinstance(l2, dict):
                    continue
                l2_name = l2.get("categoryName")
                l2_id = _coerce_int(l2.get("categoryId"))
                if l2_id is not None and isinstance(l2_name, str):
                    out[l2_id] = l2_name
                for l3 in l2.get("level3TabList") or []:
                    if not isinstance(l3, dict):
                        continue
                    l3_name = l3.get("categoryName")
                    l3_id = _coerce_int(l3.get("categoryId"))
                    if l3_id is not None and isinstance(l3_name, str):
                        out[l3_id] = l3_name
        if out:
            self.category_names = out


def _find_shop_name(components: dict) -> str | None:
    """Walk ``components`` for the entry whose ``formData.shopName.en``
    is a non-empty string. The component id rotates per page so positional
    indexing isn't safe."""
    for comp in components.values():
        if not isinstance(comp, dict):
            continue
        fd = comp.get("formData")
        if not isinstance(fd, dict):
            continue
        sn = fd.get("shopName")
        if not isinstance(sn, dict):
            continue
        en = sn.get("en")
        if isinstance(en, str) and en.strip():
            return en.strip()
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
