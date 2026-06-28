"""
Cult Kits – britisk vintage-draktbutikk (cultkits.com).
Shopify-butikk: bruker /products.json med lokal nøkkelordsfiltrering.
Bruker curl_cffi (Safari-impersonering) – httpx fikk 429 fra Cloudflare
(verifisert 2026-06-28: httpx=429, curl_cffi safari17_0=200/250 produkter).
"""

import logging
from typing import Dict, List, Optional

from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE         = "https://www.cultkits.com"
_PRODUCTS_URL = f"{_BASE}/products.json"

_product_cache: List[dict] = []


class CultKitsScraper:
    def __init__(self):
        self.client = cf.Session(impersonate="safari17_0", timeout=25)

    def search(self, keyword: str) -> List[Dict]:
        global _product_cache
        if not _product_cache:
            _product_cache = self._fetch_all()

        kw_lower = keyword.lower().replace("æ", "a")
        matches = []
        for p in _product_cache:
            title = (p.get("title") or "").lower().replace("æ", "a")
            tags  = " ".join(p.get("tags") or []).lower()
            body  = (p.get("body_html") or "").lower()[:300]
            if any(part in title or part in tags or part in body
                   for part in kw_lower.split()):
                ad = _to_ad(p)
                if ad:
                    matches.append(ad)

        logger.info("CultKits '%s': %d treff", keyword, len(matches))
        return matches

    def _fetch_all(self) -> List[dict]:
        all_products = []
        for page in range(1, 20):
            try:
                params = {"limit": 250}
                if page > 1:
                    params["page"] = page
                resp = self.client.get(_PRODUCTS_URL, params=params)
                resp.raise_for_status()
                prods = resp.json().get("products", [])
            except Exception as exc:
                logger.debug("CultKits products.json feil side %d: %s", page, exc)
                break
            if not prods:
                break
            all_products.extend(prods)
            if len(prods) < 250:
                break
        logger.debug("CultKits lager: %d produkter totalt", len(all_products))
        return all_products


def _to_ad(p: dict) -> Optional[Dict]:
    pid   = str(p.get("id") or "")
    title = (p.get("title") or "").strip()
    if not pid or not title:
        return None

    handle = p.get("handle") or pid
    url    = f"{_BASE}/products/{handle}"

    variants  = p.get("variants") or []
    price_raw = variants[0].get("price") if variants else None
    if price_raw is None:
        price_raw = p.get("price_min") or p.get("price")
    try:
        price = f"£{float(price_raw):.0f}"
    except (ValueError, TypeError):
        price = "Se pris (£)"

    imgs    = p.get("images") or []
    img_url = imgs[0].get("src") if imgs else None

    return {
        "id":          f"cultkits_{pid}",
        "source":      "cultkits.com",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": (p.get("body_html") or "")[:200],
    }
