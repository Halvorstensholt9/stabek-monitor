"""
Depop – Internasjonal second-hand plattform, populær blant draktsamlere.
Bruker Depops web-API (JSON).
"""

import logging
import urllib.parse
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_API  = "https://webapi.depop.com/api/v2/search/products/"
_BASE = "https://www.depop.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.depop.com/",
    "Origin": "https://www.depop.com",
    "depop-site-id": "gb",
}


class DepopScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        params = {
            "q": keyword,
            "itemsPerPage": 24,
            "country": "gb",
            "currency": "GBP",
            "sortBy": "NewestFirst",
        }
        try:
            resp = self.session.get(_API, params=params, timeout=20)
            if resp.status_code in (403, 429):
                logger.debug("Depop blokkerte forespørselen – 0 treff")
                return []
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Depop feil for '%s': %s", keyword, exc)
            return []

        products = data.get("products") or data.get("items") or []
        ads = [ad for ad in (_product_to_ad(p) for p in products) if ad]
        logger.info("Depop '%s': %d treff", keyword, len(ads))
        return ads


def _product_to_ad(p: dict) -> Optional[Dict]:
    pid = str(p.get("id") or p.get("slug") or "")
    if not pid:
        return None

    slug = p.get("slug") or pid
    title = (p.get("description") or "").split("\n")[0][:120].strip() or f"Depop-drakt"

    price = p.get("price") or {}
    if isinstance(price, dict):
        amount = price.get("priceAmount") or price.get("amount") or price.get("value")
        currency = price.get("currencyName") or price.get("currency") or "GBP"
        price_str = f"{amount} {currency}" if amount else "Se Depop"
    else:
        price_str = str(price) if price else "Se Depop"

    pictures = p.get("pictures") or p.get("images") or []
    img_url = None
    if pictures:
        first = pictures[0]
        if isinstance(first, dict):
            img_url = first.get("url") or first.get("src")
        elif isinstance(first, str):
            img_url = first

    url = p.get("url") or f"{_BASE}/products/{slug}/"
    if url and not url.startswith("http"):
        url = _BASE + url

    return {
        "id": f"depop_{pid}",
        "source": "depop.com",
        "title": title,
        "price": price_str,
        "url": url,
        "image_url": img_url,
        "description": p.get("description") or "",
    }
