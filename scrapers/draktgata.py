"""
Draktgata.no – norsk vintage-draktbutikk (Shopify).
Bruker Shopify /search.json som primær, /products.json som fallback.
"""

import logging
import re
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE    = "https://www.draktgata.no"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DraktMonitor/1.0)",
    "Accept": "application/json",
}


class DraktgataScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        ads, ok = self._search_shopify(keyword)
        if not ok:
            ads = self._search_products_json(keyword)
        logger.info("Draktgata '%s': %d treff", keyword, len(ads))
        return ads

    def _search_shopify(self, keyword: str):
        """Shopify /search.json – returnerer (liste, api_svarte: bool)."""
        url    = f"{_BASE}/search.json"
        params = {"q": keyword, "type": "product", "limit": 50}
        try:
            resp = self.session.get(url, params=params, timeout=20)
            if resp.status_code not in (200, 206):
                return [], False
            data = resp.json()
        except Exception:
            return [], False

        items = data.get("results") or data.get("products") or []
        return [a for a in (_to_ad(p) for p in items) if a], True

    def get_all_products(self) -> List[Dict]:
        """Henter ALLE produkter fra lageret – brukes for full lagersjekk."""
        url     = f"{_BASE}/products.json"
        all_ads = []
        # Shopify støtter page-param opp til 1000 produkter
        for page in range(1, 20):
            try:
                params = {"limit": 250}
                if page > 1:
                    params["page"] = page
                resp = self.session.get(url, params=params, timeout=20)
                resp.raise_for_status()
                products = resp.json().get("products", [])
            except Exception as exc:
                logger.debug("Draktgata get_all feil side %d: %s", page, exc)
                break
            if not products:
                break
            for p in products:
                ad = _to_ad(p)
                if ad:
                    all_ads.append(ad)
            if len(products) < 250:
                break
        logger.info("Draktgata lager: %d produkter totalt", len(all_ads))
        return all_ads

    def _search_products_json(self, keyword: str) -> List[Dict]:
        """Fallback: hent alle produkter og filtrer lokalt."""
        url    = f"{_BASE}/products.json"
        params = {"limit": 250}
        try:
            resp = self.session.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug("Draktgata products.json feil: %s", exc)
            return []

        kw_lower = keyword.lower().replace("æ", "a")
        ads = []
        for p in data.get("products", []):
            title = (p.get("title") or "").lower().replace("æ", "a")
            if any(part in title for part in kw_lower.split()):
                ad = _to_ad(p)
                if ad:
                    ads.append(ad)
        return ads


def _to_ad(p: dict) -> Optional[Dict]:
    pid   = str(p.get("id", ""))
    title = (p.get("title") or "").strip()
    if not title:
        return None

    handle = p.get("handle") or pid
    url    = f"{_BASE}/products/{handle}"

    # Pris fra første variant
    price_cents = None
    variants = p.get("variants") or []
    if variants:
        price_cents = variants[0].get("price")
    if price_cents is None:
        price_cents = p.get("price_min") or p.get("price")
    if price_cents is not None:
        try:
            price = f"{float(price_cents):.0f} kr"
        except (ValueError, TypeError):
            price = str(price_cents)
    else:
        price = "Se pris"

    imgs    = p.get("images") or []
    img_url = imgs[0].get("src") if imgs else None

    return {
        "id":          f"draktgata_{handle}",
        "source":      "draktgata.no",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": (p.get("body_html") or "")[:200],
    }
