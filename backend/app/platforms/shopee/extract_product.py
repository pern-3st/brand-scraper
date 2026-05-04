"""DOM extraction for Shopee product-detail pages.

Sibling in spirit to ``extract.py`` (which handles the shop-grid layout).
Extracts the curated enrichment catalog declared for Shopee v1:

    description, variant_options, shop_name, shop_rating,
    shop_follower_count, rating_count

Extraction is selector-tolerant: each field uses a primary DOM hook where
available, with a visible-text regex fallback so minor Shopee layout
churn doesn't silently zero-out a field.

The JS returns ``null`` for any field it can't resolve; the caller filters
to the user-requested subset and records ``null`` as a per-field error.
"""
from __future__ import annotations

from patchright.async_api import Page

# Selector seen consistently on Shopee SG product pages — the price marker
# that ``extract.py`` also relies on. We reuse it as the ready signal so
# ``navigate_with_login_wall_recovery`` has something platform-neutral to
# wait for.
PRODUCT_READY_SELECTOR = '[aria-label*="price" i]'


async def extract_product_fields(page: Page) -> dict:
    """Run ``EXTRACT_PRODUCT_JS`` against the current page and return one
    dict matching the Shopee curated catalog. Missing fields are ``None``."""
    return await page.evaluate(EXTRACT_PRODUCT_JS)


EXTRACT_PRODUCT_JS = r"""
() => {
    const out = {
        description: null,
        variant_options: null,
        shop_name: null,
        shop_rating: null,
        shop_follower_count: null,
        rating_count: null,
    };

    const root = document;
    const bodyText = (root.body && root.body.innerText) || '';

    // --- description -------------------------------------------------------
    // Shopee renders the long-form description inside a section whose
    // heading includes "Product Description". Find the heading leaf, then
    // take its nearest section/article ancestor's text.
    const headingRe = /product\s+description/i;
    for (const el of root.querySelectorAll('h1,h2,h3,div,span')) {
        if (el.children.length > 0) continue;
        const t = (el.textContent || '').trim();
        if (!headingRe.test(t)) continue;
        let cur = el;
        while (cur && cur !== root.body) {
            if (cur.tagName === 'SECTION' || cur.tagName === 'ARTICLE' ||
                (cur.getAttribute && (cur.getAttribute('role') === 'region'))) {
                break;
            }
            cur = cur.parentElement;
        }
        const host = (cur && cur !== root.body) ? cur : (el.parentElement || el);
        const text = (host.innerText || '').replace(headingRe, '').trim();
        if (text) { out.description = text; break; }
    }

    // --- variant_options ---------------------------------------------------
    // Variant chips are buttons grouped under a "Variations" label or an
    // aria-labelled radiogroup. Collect the button labels.
    const variantSet = new Set();
    for (const grp of root.querySelectorAll('[role="radiogroup"],[aria-label*="variation" i]')) {
        for (const btn of grp.querySelectorAll('button,[role="radio"]')) {
            const label = (btn.getAttribute('aria-label') || btn.textContent || '').trim();
            if (label && label.length < 80) variantSet.add(label);
        }
    }
    if (variantSet.size === 0) {
        // Fallback: "Variations" or "Options" label followed by a row of
        // button-like elements in the same container.
        for (const el of root.querySelectorAll('h1,h2,h3,div,span,label')) {
            if (el.children.length > 0) continue;
            const t = (el.textContent || '').trim();
            if (!/^\s*(variations?|options?|size|colou?r)\s*:?\s*$/i.test(t)) continue;
            const host = el.parentElement;
            if (!host) continue;
            for (const btn of host.querySelectorAll('button,[role="button"],[role="radio"]')) {
                const label = (btn.textContent || '').trim();
                if (label && label.length < 80) variantSet.add(label);
            }
            if (variantSet.size > 0) break;
        }
    }
    if (variantSet.size > 0) out.variant_options = Array.from(variantSet);

    // --- shop_name ---------------------------------------------------------
    // The shop card usually exposes a link to the shop homepage; its text
    // or aria-label carries the shop's display name.
    const shopLink = root.querySelector('a[href*="/shop/"],a[href^="/"][data-sqe*="shop" i]');
    if (shopLink) {
        const name = (shopLink.getAttribute('aria-label') || shopLink.textContent || '').trim();
        if (name && name.length < 120) out.shop_name = name;
    }

    // --- shop_rating -------------------------------------------------------
    // A "Ratings: 4.9" or "4.9" leaf adjacent to the shop card. Scope to
    // any element whose aria-label mentions "rating".
    const ratingCandidates = [];
    for (const el of root.querySelectorAll('[aria-label*="rating" i]')) {
        ratingCandidates.push((el.getAttribute('aria-label') || '') + ' ' + (el.textContent || ''));
    }
    for (const src of ratingCandidates) {
        const m = src.match(/(\d(?:\.\d)?)\s*(?:\/\s*5)?/);
        if (!m) continue;
        const v = parseFloat(m[1]);
        if (v >= 0 && v <= 5) { out.shop_rating = v; break; }
    }

    // --- shop_follower_count ----------------------------------------------
    // Visible string like "Followers 1.2k" or "1.2k Followers". Covers both
    // orderings with a single regex.
    const followersMatch = bodyText.match(
        /(?:followers?\s*[:\-]?\s*)(\d+(?:[.,]\d+)?)\s*([kKmM]?)|(\d+(?:[.,]\d+)?)\s*([kKmM]?)\s*followers?/i
    );
    if (followersMatch) {
        const num = followersMatch[1] || followersMatch[3];
        const suf = (followersMatch[2] || followersMatch[4] || '').toLowerCase();
        let n = parseFloat(num.replace(',', '.'));
        if (suf === 'k') n *= 1000;
        else if (suf === 'm') n *= 1000000;
        out.shop_follower_count = Math.round(n);
    }

    // --- rating_count ------------------------------------------------------
    // "(1,234 ratings)" or "1.2k Ratings" — sits near the product's own rating
    // score, not the shop's. Grab the first match in body text.
    const rcMatch = bodyText.match(
        /(\d+(?:[.,]\d+)?)\s*([kKmM]?)\s*(?:product\s*)?ratings?\b/i
    );
    if (rcMatch) {
        let n = parseFloat(rcMatch[1].replace(/,/g, ''));
        const suf = (rcMatch[2] || '').toLowerCase();
        if (suf === 'k') n *= 1000;
        else if (suf === 'm') n *= 1000000;
        out.rating_count = Math.round(n);
    }

    return out;
}
"""
