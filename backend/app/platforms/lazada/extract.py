"""Pure-function extraction helpers for the Lazada catalog.

The shop SPA picks one of three catalog endpoints depending on whether
the shop has an active campaign. Per-item shape is identical across all
three; only the response envelope differs:

  - campaignTppProducts/query        →  ``result.data[]``
  - mtop.lazada.shop.tpp.query.justforyou/1.0/  →  ``data.result.data.products[]``
  - mtop.lazada.shop.smart.products.query/1.0/  →  ``data.result.data[]``

``parse_catalog_response`` detects the envelope shape and returns the
items list. ``map_item`` runs the shared per-item field mapping; the
result dict can be passed straight into ``LazadaProductRecord(**dict)``
after metadata enrichment.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# URL fragments matched against ``response.url`` in the live listener.
# Order doesn't matter; each is independent.
CATALOG_URL_FRAGMENTS = (
    "/shop/site/api/shop/campaignTppProducts/query",
    "/h5/mtop.lazada.shop.tpp.query.justforyou/",
    "/h5/mtop.lazada.shop.smart.products.query/",
)


def is_catalog_url(url: str) -> bool:
    return any(frag in url for frag in CATALOG_URL_FRAGMENTS)


def parse_catalog_response(payload: Any) -> list[dict]:
    """Extract the items list from any of the three known envelope shapes.

    Returns an empty list when the shape is unrecognised or the items
    list is missing. The caller logs at debug level when this happens.
    """
    if not isinstance(payload, dict):
        return []

    # Campaign endpoint: result.data[]
    result = payload.get("result")
    if isinstance(result, dict):
        items = result.get("data")
        if isinstance(items, list):
            return [it for it in items if isinstance(it, dict)]

    # mtop endpoints share the data.result envelope. Either:
    #   data.result.data.products[]   (justforyou)
    #   data.result.data[]            (smart.products)
    data = payload.get("data")
    if isinstance(data, dict):
        inner = data.get("result")
        if isinstance(inner, dict):
            inner_data = inner.get("data")
            # justforyou: dict with "products"
            if isinstance(inner_data, dict):
                products = inner_data.get("products")
                if isinstance(products, list):
                    return [it for it in products if isinstance(it, dict)]
            # smart.products: list directly
            if isinstance(inner_data, list):
                return [it for it in inner_data if isinstance(it, dict)]

    return []


def map_item(item: dict) -> dict | None:
    """Convert one catalog item into the field-level dict consumed by
    ``LazadaProductRecord``. Returns ``None`` when required identifying
    fields are missing.

    All metadata-resolution fields (brand_name, category_name,
    category_lineage) are left absent — ``MetadataResolver.enrich``
    fills them in afterwards.
    """
    auction_id = item.get("auctionId")
    title = item.get("title")
    pdp_url = item.get("pdpUrl")
    if not isinstance(auction_id, int) or not isinstance(title, str) or not isinstance(pdp_url, str):
        return None

    # Image is protocol-relative in the payload (//sg-test-11.slatic.net/...).
    image_url = item.get("imageUrl")
    if isinstance(image_url, str) and image_url.startswith("//"):
        image_url = f"https:{image_url}"

    discount_raw = item.get("discount")
    discount_pct: int | None = None
    if isinstance(discount_raw, (int, float)):
        discount_pct = int(round(float(discount_raw)))

    # Promotion labels: recommendTexts[].titleText, filtered to strings.
    rec_texts = item.get("recommendTexts") or []
    promotion_labels: list[str] = []
    if isinstance(rec_texts, list):
        for rt in rec_texts:
            if isinstance(rt, dict):
                title_text = rt.get("titleText")
                if isinstance(title_text, str) and title_text:
                    promotion_labels.append(title_text)

    categories = item.get("categories") or []
    if not isinstance(categories, list):
        categories = []

    out: dict = {
        # Base fields
        "product_name": title,
        "product_url": pdp_url,
        "image_url": image_url if isinstance(image_url, str) else None,
        "price": _as_float(item.get("discountPrice")) or _as_float(item.get("price")),
        "mrp": _as_float(item.get("price")),
        "currency": "SGD",
        "discount_pct": discount_pct,
        "is_sold_out": item.get("inStock") == 0,

        # Identification
        "item_id": auction_id,
        "sku_id": item.get("skuId") if isinstance(item.get("skuId"), int) else None,
        "sku": item.get("sku") if isinstance(item.get("sku"), str) else None,

        # Pricing extras
        "saved_text": item.get("savedText") if isinstance(item.get("savedText"), str) else None,

        # Promotion
        "hit_promotion": item.get("hitPromotion") if isinstance(item.get("hitPromotion"), str) else None,
        "promotion_start_time": item.get("promotionStartTime") if isinstance(item.get("promotionStartTime"), int) else None,
        "promotion_end_time": item.get("promotionEndTime") if isinstance(item.get("promotionEndTime"), int) else None,
        "promotion_labels": promotion_labels,

        # Stock & shipping
        "free_shipping": bool(item.get("freeShipping", False)),
        "mall": bool(item.get("mall", False)),

        # Popularity / reviews
        "rating": _as_float(item.get("rating")),
        "review_count": item.get("reviews") if isinstance(item.get("reviews"), int) else None,
        "volume_monthly": item.get("volumePayOrdPrdQty1m") if isinstance(item.get("volumePayOrdPrdQty1m"), int) else None,
        "volume_weekly": item.get("volumePayOrdPrdQty1w") if isinstance(item.get("volumePayOrdPrdQty1w"), int) else None,
        "volume_total": item.get("volumePayOrdPrdQtyStd") if isinstance(item.get("volumePayOrdPrdQtyStd"), int) else None,

        # Shop / brand / category — IDs only here; *_name fields are added
        # later by the metadata resolver.
        "shop_id": item.get("shopId") if isinstance(item.get("shopId"), int) else None,
        "seller_id": item.get("sellerId") if isinstance(item.get("sellerId"), int) else None,
        "brand_id": item.get("brandId") if isinstance(item.get("brandId"), int) else None,
        "category_id": item.get("categoryId") if isinstance(item.get("categoryId"), int) else None,
        # Stash the int lineage for MetadataResolver.enrich() to translate
        # into names; not a record field. The resolver pops it before the
        # dict is fed to LazadaProductRecord.
        "_category_id_lineage": [c for c in categories if isinstance(c, int)],
    }
    return out


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def shop_handle_from_url(shop_url: str) -> str:
    """``https://www.lazada.sg/shop/lacoste/?path=...`` → ``"lacoste"``.

    Raises ``ValueError`` for non-lazada.sg hosts or paths that don't
    contain a ``/shop/<handle>/`` segment.
    """
    parsed = urlparse(shop_url)
    host = (parsed.hostname or "").lower()
    if host not in {"lazada.sg", "www.lazada.sg"}:
        raise ValueError(
            f"lazada: shop_url host {host!r} is not lazada.sg "
            f"(other regions are out of scope for the SG-only profile)"
        )
    parts = [p for p in parsed.path.split("/") if p]
    # Expect ["shop", "<handle>", ...]
    if len(parts) < 2 or parts[0] != "shop":
        raise ValueError(
            f"lazada: shop_url path {parsed.path!r} does not match /shop/<handle>/"
        )
    return parts[1]
