"""
Blocket.se – Svensk finn.no-ekvivalent.
Bruker Blockets interne JSON-API.
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_API  = "https://api.blocket.se/search_bff/v2/content"
_BASE = "https://www.blocket.se"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
    "Accept-Language": "sv-SE,sv;q=0.9",
    "Origin": "https://www.blocket.se",
    "Referer": "https://www.blocket.se/",
}


class BlocketScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        params = {
            "q": keyword,
            "lim": 40,
            "st": "s",         # kjøp/selg
            "sort": "date",
        }
        try:
            resp = self.session.get(_API, params=params, timeout=20)
            if resp.status_code in (401, 403):
                logger.debug("Blocket API blokkerte – 0 treff")
                return []
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Blocket feil for '%s': %s", keyword, exc)
            return []

        items = data.get("data") or []
        ads = [ad for ad in (_item_to_ad(i) for i in items) if ad]
        logger.info("Blocket '%s': %d treff", keyword, len(ads))
        return ads


def _item_to_ad(i: dict) -> Optional[Dict]:
    ad_id = str(i.get("ad_id") or i.get("id") or "")
    if not ad_id:
        return None

    title = (i.get("subject") or i.get("title") or "").strip()
    if not title:
        return None

    price = i.get("price") or {}
    if isinstance(price, dict):
        amount = price.get("value") or price.get("amount")
        unit = price.get("unit") or "SEK"
        price_str = f"{amount} {unit}" if amount else "Se pris"
    else:
        price_str = str(price) if price else "Se pris"

    images = i.get("images") or i.get("image_urls") or []
    img_url = None
    if images:
        first = images[0]
        img_url = first.get("url") if isinstance(first, dict) else str(first)
        if img_url and img_url.startswith("//"):
            img_url = "https:" + img_url

    share_url = i.get("share_url") or i.get("url") or f"{_BASE}/annons/{ad_id}"

    return {
        "id": f"blocket_{ad_id}",
        "source": "blocket.se",
        "title": title,
        "price": price_str,
        "url": share_url,
        "image_url": img_url,
        "description": i.get("body") or "",
    }
