"""
Marktplaats.nl – nederlandsk bruktmarked (nest størst i Europa).
Bruker Marktplaats JSON search API.
"""

import logging
import urllib.parse
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_API_URL = "https://www.marktplaats.nl/lrp/api/search"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}


class MarktplaatsScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        params = {
            "query": keyword,
            "searchInTitleAndDescription": "true",
            "limit": 30,
            "offset": 0,
            "sortBy": "SORT_INDEX",
            "sortOrder": "DECREASING",
        }
        try:
            resp = self.session.get(_API_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug("Marktplaats feil for '%s': %s", keyword, exc)
            return []

        ads = [a for a in (_listing_to_ad(l) for l in data.get("listings", [])) if a]
        logger.info("Marktplaats '%s': %d treff", keyword, len(ads))
        return ads


def _listing_to_ad(item: dict) -> Optional[Dict]:
    item_id = str(item.get("itemId", ""))
    title   = (item.get("title") or "").strip()
    if not item_id or not title:
        return None

    vip_url = item.get("vipUrl") or ""
    url     = f"https://www.marktplaats.nl{vip_url}" if vip_url.startswith("/") else vip_url

    price_info  = item.get("priceInfo") or {}
    price_cents = price_info.get("priceCents")
    if price_cents is not None:
        price = f"€{price_cents / 100:.0f}"
    else:
        price = price_info.get("priceType", "Se pris")

    pics    = item.get("pictures") or item.get("imageUrls") or []
    img_url = None
    if pics:
        first = pics[0]
        if isinstance(first, dict):
            img_url = first.get("mediumUrl") or first.get("largeUrl") or first.get("extraExtraLargeUrl")
        elif isinstance(first, str):
            img_url = first

    desc = (item.get("description") or "")[:200]

    return {
        "id":          f"marktplaats_{item_id}",
        "source":      "marktplaats.nl",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": desc,
    }
