"""
Classickits.no – norsk nettbutikk for retro/klassiske fotballdrakter (Shopify).
Bruker products.json med 15-min TTL-cache (samme som Forza).
"""

import logging
import re
import time
from typing import Dict, List, Optional

from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE         = "https://classickits.no"
_PRODUCTS_URL = f"{_BASE}/products.json"

_product_cache: List[dict] = []
_cache_fetched_at: float   = 0.0
_CACHE_TTL: float          = 15 * 60


def _norm(s: str) -> str:
    return s.lower().replace("æ", "a").replace("ø", "o").replace("å", "a")


class ClassicKitsNoScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="safari17_0")

    def search(self, keyword: str) -> List[Dict]:
        global _product_cache, _cache_fetched_at
        if not _product_cache or time.time() - _cache_fetched_at > _CACHE_TTL:
            _product_cache    = self._fetch_all()
            _cache_fetched_at = time.time()

        kw = _norm(keyword)
        matches = []
        for p in _product_cache:
            title = _norm(p.get("title") or "")
            tags  = _norm(" ".join(p.get("tags") or []))
            body  = _norm((p.get("body_html") or "")[:400])
            if kw not in title and kw not in tags and kw not in body:
                continue
            variants  = p.get("variants") or []
            available = any(v.get("available", False) for v in variants)
            if not available:
                continue
            ad = _to_ad(p)
            if ad:
                matches.append(ad)
        logger.info("Classickits.no '%s': %d treff", keyword, len(matches))
        return matches

    def _fetch_all(self) -> List[dict]:
        all_products = []
        for page in range(1, 20):
            try:
                params = {"limit": 250}
                if page > 1: params["page"] = page
                resp = self.session.get(_PRODUCTS_URL, params=params, timeout=30)
                resp.raise_for_status()
                prods = resp.json().get("products", [])
            except Exception as exc:
                logger.debug("Classickits.no products.json feil side %d: %s", page, exc)
                break
            if not prods: break
            all_products.extend(prods)
            if len(prods) < 250: break
        logger.info("Classickits.no lager oppdatert: %d produkter", len(all_products))
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
        price = f"kr {float(price_raw):.0f}"
    except (ValueError, TypeError):
        price = "Se pris"
    imgs    = p.get("images") or []
    img_url = imgs[0].get("src") if imgs else None
    body_clean = re.sub(r"<[^>]+>", " ", (p.get("body_html") or "")[:300]).strip()
    return {
        "id":          f"classickitsno_{pid}",
        "source":      "classickits.no",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": body_clean,
    }
