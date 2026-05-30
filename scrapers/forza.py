"""
Forzasecondhand.no-scraper.
Norsk spesialistside for brukte fotballdrakter (Shopify).
Bruker curl_cffi for å etterligne Chrome-fingerprint og omgå Cloudflare.
"""

import logging
import time
from typing import Dict, List, Optional

from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE         = "https://forzasecondhand.no"
_PRODUCTS_URL = f"{_BASE}/products.json"

# ── Cache med TTL ────────────────────────────────────────────────────────────
# Oppdateres hvert 15. minutt så nye Stabæk-drakter fanges raskt.
_product_cache: List[dict] = []
_cache_fetched_at: float   = 0.0
_CACHE_TTL: float          = 15 * 60   # sekunder


def _norm(s: str) -> str:
    """Normaliser: lowercase + fjern norske tegn for sammenligning."""
    return s.lower().replace("æ", "a").replace("ø", "o").replace("å", "a")


class ForzaScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="chrome124")

    def search(self, keyword: str) -> List[Dict]:
        global _product_cache, _cache_fetched_at

        # Hent/oppdater cache hvis nødvendig
        age = time.time() - _cache_fetched_at
        if not _product_cache or age > _CACHE_TTL:
            _product_cache    = self._fetch_all()
            _cache_fetched_at = time.time()

        kw_norm = _norm(keyword)
        matches = []

        for p in _product_cache:
            title = _norm(p.get("title") or "")
            tags  = _norm(" ".join(p.get("tags") or []))
            body  = _norm((p.get("body_html") or "")[:400])

            # ── Treffsjekk: hel frase, ikke split-ord ────────────────────
            # "stabæk IF" → søker etter "stabak if" som helhet, ikke "stabak" + "if"
            # slik at generiske ord som "if", "k" ikke gir falske treff.
            if kw_norm not in title and kw_norm not in tags and kw_norm not in body:
                continue

            # ── Kun TILGJENGELIGE varer ───────────────────────────────────
            # Hopp over utsolgte/solgte produkter
            variants  = p.get("variants") or []
            available = any(v.get("available", False) for v in variants)
            if not available:
                continue

            ad = _to_ad(p)
            if ad:
                matches.append(ad)

        logger.info("Forzasecondhand '%s': %d treff", keyword, len(matches))
        return matches

    def _fetch_all(self) -> List[dict]:
        all_products = []
        for page in range(1, 30):
            try:
                params = {"limit": 250}
                if page > 1:
                    params["page"] = page
                resp = self.session.get(_PRODUCTS_URL, params=params, timeout=30)
                resp.raise_for_status()
                prods = resp.json().get("products", [])
            except Exception as exc:
                logger.debug("Forza products.json feil side %d: %s", page, exc)
                break
            if not prods:
                break
            all_products.extend(prods)
            logger.debug("Forza: side %d – %d produkter (total %d)",
                         page, len(prods), len(all_products))
            if len(prods) < 250:
                break
        logger.info("Forza lager oppdatert: %d produkter totalt", len(all_products))
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

    # Rens body_html for HTML-tagger
    body_raw = (p.get("body_html") or "")[:300]
    import re as _re
    body_clean = _re.sub(r"<[^>]+>", " ", body_raw).strip()

    return {
        "id":          f"forza_{pid}",
        "source":      "forzasecondhand.no",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": body_clean,
    }
