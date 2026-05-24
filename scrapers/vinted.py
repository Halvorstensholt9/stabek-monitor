"""
Vinted.no-scraper.
Bruker Vinteds offentlige søke-API (JSON).
Vinted har anti-bot-beskyttelse – feiler den, prøver vi HTML-fallback.
"""

import json
import logging
import re
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Vinted bruker vinted.com (ingen .no-domene) – norske brukere
# havner automatisk på norsk versjon basert på IP/språk
_API_URL = "https://www.vinted.com/api/v2/catalog/items"
_SEARCH_URL = "https://www.vinted.com/catalog"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.vinted.com/",
    "Origin": "https://www.vinted.com",
}


class VintedScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        # Prøv JSON-API først
        ads = self._search_api(keyword)
        if ads is not None:  # None = feilet, [] = ingen treff
            logger.info("Vinted '%s': %d treff (API)", keyword, len(ads))
            return ads

        # Fallback: HTML-parsing
        ads = self._search_html(keyword)
        logger.info("Vinted '%s': %d treff (HTML)", keyword, len(ads))
        return ads

    def _search_api(self, keyword: str) -> Optional[List[Dict]]:
        params = {
            "search_text": keyword,
            "order": "newest_first",
            "per_page": "60",
        }
        url = f"{_API_URL}?{urllib.parse.urlencode(params)}"
        try:
            resp = self.session.get(url, timeout=20)
            if resp.status_code in (401, 403):
                logger.debug("Vinted API blokkerte forespørselen – prøver HTML")
                return None
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.debug("Vinted API feil: %s – prøver HTML", exc)
            return None

        items = data.get("items") or []
        return [ad for ad in (_vinted_item_to_ad(i) for i in items) if ad]

    def _search_html(self, keyword: str) -> List[Dict]:
        params = {"search_text": keyword, "order": "newest_first"}
        url = f"{_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Vinted HTML feil for '%s': %s", keyword, exc)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        # Vinted React-app – se etter JSON i script-tagger
        for script in soup.find_all("script"):
            text = script.string or ""
            if '"items"' in text and '"title"' in text:
                try:
                    # Finn første JSON-objekt med items
                    m = re.search(r'"items"\s*:\s*(\[.+?\])\s*[,}]', text, re.DOTALL)
                    if m:
                        items = json.loads(m.group(1))
                        for item in items:
                            ad = _vinted_item_to_ad(item)
                            if ad:
                                results.append(ad)
                        if results:
                            return results
                except (json.JSONDecodeError, Exception):
                    pass

        # Siste utvei: lenker til produkt-sider
        for a_tag in soup.find_all("a", href=re.compile(r"/items/\d+")):
            ad = _vinted_link_to_ad(a_tag)
            if ad:
                results.append(ad)

        return results


def _vinted_item_to_ad(item: dict) -> Optional[Dict]:
    item_id = str(item.get("id") or "")
    if not item_id:
        return None

    title = (item.get("title") or "Vinted-annonse").strip()

    price = item.get("price") or {}
    if isinstance(price, dict):
        amount = price.get("amount") or price.get("numeric")
        currency = price.get("currency_code") or "kr"
        price_str = f"{amount} {currency}" if amount else "Se Vinted"
    elif price:
        price_str = str(price)
    else:
        price_str = "Se Vinted"

    photos = item.get("photos") or []
    img_url = None
    if photos:
        first = photos[0] if isinstance(photos, list) else photos
        if isinstance(first, dict):
            img_url = (first.get("full_size_url") or
                       first.get("url") or
                       (first.get("thumbnails") or [{}])[-1].get("url"))
        elif isinstance(first, str):
            img_url = first

    url = item.get("url") or f"https://www.vinted.no/items/{item_id}"
    if url and not url.startswith("http"):
        url = "https://www.vinted.no" + url

    return {
        "id": f"vinted_{item_id}",
        "source": "vinted.no",
        "title": title,
        "price": price_str,
        "url": url,
        "image_url": img_url,
        "description": item.get("description") or "",
    }


def _vinted_link_to_ad(tag) -> Optional[Dict]:
    href = tag.get("href", "")
    m = re.search(r"/items/(\d+)", href)
    if not m:
        return None
    item_id = m.group(1)
    url = f"https://www.vinted.no{href}" if not href.startswith("http") else href
    img = tag.find("img")
    title = (img.get("alt") if img else None) or tag.get_text(strip=True)[:120] or "Vinted-annonse"
    img_url = (img.get("src") or img.get("data-src")) if img else None
    return {
        "id": f"vinted_{item_id}",
        "source": "vinted.no",
        "title": title,
        "price": "Se Vinted",
        "url": url,
        "image_url": img_url,
        "description": "",
    }
