"""
Catawiki – internasjonal auksjon for samlergjenstander inkl. fotballdrakter.
Prøver JSON-API først, deretter HTML-parsing.
"""

import json
import logging
import re
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE    = "https://www.catawiki.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,no;q=0.8",
    "Referer":         "https://www.catawiki.com/",
    "sec-ch-ua":        '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest":  "document",
    "sec-fetch-mode":  "navigate",
    "sec-fetch-site":  "same-origin",
    "Cache-Control":   "no-cache",
    "Pragma":          "no-cache",
}

# Catawiki public lot-search API (brukes av deres egne sider)
_API_URL = "https://www.catawiki.com/buyer/api/v1/lots"


class CatawikiScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        # Prøv interne API-et først, deretter HTML
        ads = self._try_api(keyword) or self._try_html(keyword)
        logger.info("Catawiki '%s': %d treff", keyword, len(ads))
        return ads

    def _try_api(self, keyword: str) -> List[Dict]:
        """Catawikis interne lot-søk API."""
        params = {
            "query":    keyword,
            "sort":     "lot_end_at_desc",
            "per_page": 30,
            "page":     1,
        }
        headers = dict(self.session.headers)
        headers["Accept"] = "application/json"
        headers["X-Requested-With"] = "XMLHttpRequest"
        try:
            resp = self.session.get(_API_URL, params=params, headers=headers, timeout=20)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:
            return []

        lots = data.get("lots") or data.get("data") or data.get("results") or []
        ads  = [a for a in (_lot_to_ad(lot) for lot in lots) if a]

        # Filtrer på søkeord
        kw_parts = keyword.lower().replace("æ", "a").split()
        return [ad for ad in ads if any(p in ad["title"].lower().replace("æ", "a") for p in kw_parts)]

    def _try_html(self, keyword: str) -> List[Dict]:
        url    = f"{_BASE}/en/l/search"
        params = {"q": keyword, "sort": "time_listed_desc"}
        try:
            resp = self.session.get(url, params=params, timeout=25)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.debug("Catawiki HTML feil for '%s': %s", keyword, exc)
            return []

        ads = _parse_next_data(resp.text) or _parse_html(resp.text)

        kw_parts = keyword.lower().replace("æ", "a").split()
        return [ad for ad in ads if any(p in ad["title"].lower().replace("æ", "a") for p in kw_parts)]


def _parse_next_data(html: str) -> List[Dict]:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    try:
        data  = json.loads(m.group(1))
        # Finn lots-/items-lister rekursivt
        items = _find_lots(data)
        return [a for a in (_lot_to_ad(i) for i in items) if a]
    except Exception:
        return []


def _find_lots(obj, depth=0):
    """Rekursivt søk etter lot/item-lister i __NEXT_DATA__."""
    if depth > 8:
        return []
    if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
        first = obj[0]
        if any(k in first for k in ("lotId", "lot_id", "id", "slug", "title")):
            return obj
    if isinstance(obj, dict):
        for v in obj.values():
            result = _find_lots(v, depth + 1)
            if result:
                return result
    return []


def _lot_to_ad(item: dict) -> Optional[Dict]:
    lot_id = str(item.get("lotId") or item.get("lot_id") or item.get("id") or "")
    title  = item.get("title") or item.get("name") or item.get("objectTitle") or ""
    if not lot_id or not title:
        return None

    slug = item.get("slug") or item.get("handle") or lot_id
    url  = f"{_BASE}/en/l/{slug}"

    # Pris
    price_data = item.get("reservePrice") or item.get("estimatedValue") or {}
    if isinstance(price_data, dict):
        val  = price_data.get("amount") or price_data.get("value") or ""
        curr = price_data.get("currency") or "€"
        price = f"{curr} {val}" if val else "Se auksjon"
    else:
        price = str(price_data) if price_data else "Se auksjon"

    # Bilde
    photos  = item.get("photos") or item.get("images") or []
    img_url = None
    if photos:
        first = photos[0]
        img_url = first.get("full") or first.get("medium") or first.get("url") or (
            first if isinstance(first, str) else None
        )

    return {
        "id":          f"catawiki_{lot_id}",
        "source":      "catawiki.com",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": item.get("description", "")[:200],
    }


def _parse_html(html: str) -> List[Dict]:
    soup    = BeautifulSoup(html, "lxml")
    results = []

    # Prøv ulike article/card-selectors
    candidates = (
        soup.find_all("article") or
        soup.select("[class*='LotCard'], [class*='lot-card'], [class*='lot_card']") or
        soup.find_all("li", attrs={"data-lot-id": True}) or
        soup.find_all(attrs={"data-lot-id": True})
    )

    for item in candidates:
        ad = _html_item_to_ad(item)
        if ad:
            results.append(ad)
    return results


def _html_item_to_ad(item) -> Optional[Dict]:
    link = item.find("a", href=re.compile(r"/en/l/|/lot/|\d{6,}"))
    if not link:
        link = item.find("a", href=True)
    if not link:
        return None

    href = link.get("href", "")
    url  = (_BASE + href) if not href.startswith("http") else href

    m      = re.search(r"/(\d{6,})", href)
    ad_id  = m.group(1) if m else re.sub(r"[^\w]", "_", href)[:40]

    title_tag = (
        item.find(class_=re.compile(r"title|name|heading|object", re.I)) or
        item.find("h2") or item.find("h3") or link
    )
    title = title_tag.get_text(strip=True) if title_tag else ""
    if not title:
        return None

    price_tag = item.find(class_=re.compile(r"price|bid|estimate|reserve", re.I))
    price     = price_tag.get_text(strip=True) if price_tag else "Se auksjon"

    img     = item.find("img")
    img_url = None
    if img:
        img_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src")

    return {
        "id":          f"catawiki_{ad_id}",
        "source":      "catawiki.com",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": "",
    }
