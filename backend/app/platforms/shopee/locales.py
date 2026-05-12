"""Per-region Shopee locale config.

Single source of truth for currency-glyph and number-format quirks
across Shopee markets. Used by ``extract.py`` to parse prices off the
shop grid and by ``scraper.py`` to populate ``ShopeeProductRecord.currency``.

To onboard a new region:
  1. Open a shop URL in that region and inspect a price card (the
     ``[aria-label*="price"]`` element's parent.innerText).
  2. Note the glyph, whether it precedes or follows the number, and
     which character is thousands vs decimal separator.
  3. Add a row below keyed by the bare hostname (no ``www.``).

Number-format reference (en-US convention vs locale-native):
  SG/MY/PH/TH render prices English-style: ``RM1,234.56`` — comma is
  thousands, dot is decimal.
  VN/ID render European-style: ``Rp12.345`` / ``1.234.567₫`` — dot is
  thousands. VND has no fractional units in practice; IDR shows decimals
  rarely.
"""
from __future__ import annotations

from urllib.parse import urlparse

LOCALES: dict[str, dict] = {
    "shopee.sg":     {"currency": "SGD", "glyph": "S$", "glyph_pos": "prefix", "thousands": ",", "decimal": "."},
    "shopee.com.my": {"currency": "MYR", "glyph": "RM", "glyph_pos": "prefix", "thousands": ",", "decimal": "."},
    "shopee.ph":     {"currency": "PHP", "glyph": "₱",  "glyph_pos": "prefix", "thousands": ",", "decimal": "."},
    "shopee.co.th":  {"currency": "THB", "glyph": "฿",  "glyph_pos": "prefix", "thousands": ",", "decimal": "."},
    "shopee.vn":     {"currency": "VND", "glyph": "₫",  "glyph_pos": "suffix", "thousands": ".", "decimal": ","},
    "shopee.co.id":  {"currency": "IDR", "glyph": "Rp", "glyph_pos": "prefix", "thousands": ".", "decimal": ","},
}


def resolve_locale(shop_url: str) -> dict:
    host = (urlparse(shop_url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in LOCALES:
        raise ValueError(
            f"unknown Shopee locale for host {host!r}; "
            f"add it to LOCALES in app/platforms/shopee/locales.py"
        )
    return LOCALES[host]
