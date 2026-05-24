"""
Tradera.se – Svensk bruktmarkedsplass (som Finn.no).
Bruker Traderas søke-API som returnerer JSON.
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_API  = "https://www.tradera.com/api/search/search"
_BASE = "https://www.tradera.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "sv-SE,sv;q=0.9,no;q=0.8,en;q=0.6",
    "Referer": "https://www.tradera.com/",
}


class TraderaScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        ads = self._search_api(keyword)
        if ads is None:
            ads = self._search_html(keyword)
        logger.info("Tradera '%s': %d treff", keyword, len(ads))
        return ads

    def _search_api(self, keyword: str) -> Optional[List[Dict]]:
        params = {"q": keyword, "saleType": "all", "orderBy": "AddedOn_Desc"}
        try:
            resp = self.session.get(_API, params=params, timeout=20)
            if resp.status_code in (403, 404):
                return None
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return None

        items = (data.get("items") or data.get("result") or
                 data.get("data", {}).get("items") or [])
        return [ad for ad in (_api_item(i) for i in items) if ad]

    def _search_html(self, keyword: str) -> List[Dict]:
        url = f"{_BASE}/search?query={urllib.parse.quote(keyword)}"
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Tradera HTML-feil for '%s': %s", keyword, exc)
            return []
        return _parse_tradera_html(resp.text)


def _api_item(i: dict) -> Optional[Dict]:
    item_id = str(i.get("id") or i.get("itemId") or "")
    if not item_id:
        return None
    title = (i.get("shortDescription") or i.get("title") or "").strip()
    if not title:
        return None
    price_val = (i.get("buyNowPrice") or i.get("currentBid") or
                 i.get("startingBid") or i.get("price") or {})
    if isinstance(price_val, dict):
        price_str = f"{price_val.get('amount', '')} {price_val.get('unit', 'SEK')}".strip()
    else:
        price_str = f"{price_val} SEK" if price_val else "Se bud"

    thumb = i.get("thumbnailLink") or i.get("imageUrl") or ""
    img_url = ("https:" + thumb) if thumb.startswith("//") else (thumb or None)

    slug = i.get("itemUrl") or i.get("url") or f"/item/{item_id}"
    url = (_BASE + slug) if not slug.startswith("http") else slug

    return {
        "id": f"tradera_{item_id}",
        "source": "tradera.se",
        "title": title,
        "price": price_str,
        "url": url,
        "image_url": img_url,
        "description": i.get("description") or "",
    }


def _parse_tradera_html(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.find_all("a", href=re.compile(r"/item/\d+")):
        href = card["href"]
        url = (_BASE + href) if not href.startswith("http") else href
        m = re.search(r"/item/(\d+)", href)
        ad_id = m.group(1) if m else href
        img = card.find("img")
        title = (img.get("alt") if img else None) or card.get_text(strip=True)[:120]
        img_url = (img.get("src") or img.get("data-src")) if img else None
        if not title:
            continue
        results.append({
            "id": f"tradera_{ad_id}",
            "source": "tradera.se",
            "title": title,
            "price": "Se bud",
            "url": url,
            "image_url": img_url,
            "description": "",
        })
    return results
