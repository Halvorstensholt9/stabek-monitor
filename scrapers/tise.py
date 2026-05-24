"""
Tise-scraper.
Tise er Norges største bruktapp for klær og utstyr.
Søke-URL: https://tise.com/search?query=QUERY
"""

import json
import logging
import re
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Tise prøver disse URL-ene i rekkefølge til én returnerer 200
_SEARCH_CANDIDATES = [
    ("https://tise.com/search",   "q"),
    ("https://tise.com/search",   "query"),
    ("https://tise.com/listings", "q"),
    ("https://tise.com/explore",  "q"),
]
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.6",
}


class TiseScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        resp = self._fetch(keyword)
        if resp is None:
            return []
        ads = self._parse_next_data(resp.text) or self._parse_html(resp.text)
        logger.info("Tise '%s': %d treff", keyword, len(ads))
        return ads

    def _fetch(self, keyword: str):
        """Prøver URL-kandidatene til én returnerer 200."""
        for base_url, param in _SEARCH_CANDIDATES:
            url = f"{base_url}?{urllib.parse.urlencode({param: keyword})}"
            try:
                resp = self.session.get(url, timeout=20)
                if resp.status_code == 200:
                    logger.debug("Tise treffer på: %s", url)
                    return resp
                logger.debug("Tise %s returnerte %d", url, resp.status_code)
            except requests.RequestException as exc:
                logger.debug("Tise %s feil: %s", url, exc)
        logger.warning("Tise: ingen URL-kandidat fungerte for '%s'", keyword)
        return None

    # ── JSON-strategi (Next.js) ───────────────────────────────────────────

    def _parse_next_data(self, html: str) -> List[Dict]:
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("script", id="__NEXT_DATA__")
        if not tag or not tag.string:
            return []
        try:
            data = json.loads(tag.string)
        except json.JSONDecodeError:
            return []

        items = _find_items(data)
        if not items:
            return []
        return [ad for ad in (_item_to_ad(i) for i in items) if ad]

    # ── HTML-fallback ────────────────────────────────────────────────────

    def _parse_html(self, html: str) -> List[Dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        for a_tag in soup.find_all("a", href=re.compile(r"/(listing|item)/", re.I)):
            ad = _card_to_ad(a_tag)
            if ad:
                results.append(ad)
        return results


def _item_to_ad(item: dict) -> Optional[Dict]:
    if not isinstance(item, dict):
        return None

    item_id = str(item.get("id") or item.get("uuid") or "")
    if not item_id:
        return None

    title = (item.get("title") or "").strip() or (
        (item.get("description") or "").split("\n")[0][:120]
    ) or "Tise-annonse"

    price_raw = item.get("price") or item.get("priceNOK") or item.get("amount") or {}
    if isinstance(price_raw, dict):
        amount = price_raw.get("amount") or price_raw.get("value")
        price_str = f"{amount} kr" if amount else "Se Tise"
    elif price_raw:
        price_str = f"{price_raw} kr"
    else:
        price_str = "Se Tise"

    photos = item.get("photos") or item.get("images") or []
    img_url = None
    if photos:
        first = photos[0] if isinstance(photos, list) else photos
        if isinstance(first, dict):
            img_url = (first.get("url") or first.get("src") or
                       first.get("medium") or first.get("thumbnail"))
        elif isinstance(first, str):
            img_url = first

    slug = item.get("slug") or item.get("url") or item_id
    if slug and slug.startswith("http"):
        url = slug
    else:
        url = f"https://tise.com/listing/{slug}"

    return {
        "id": f"tise_{item_id}",
        "source": "tise.com",
        "title": title,
        "price": price_str,
        "url": url,
        "image_url": img_url,
        "description": (item.get("description") or ""),
    }


def _card_to_ad(tag) -> Optional[Dict]:
    href = tag.get("href", "")
    if not href:
        return None
    url = f"https://tise.com{href}" if not href.startswith("http") else href
    m = re.search(r"/(listing|item)/([^/?#]+)", href)
    ad_id = m.group(2) if m else re.sub(r"[^a-z0-9]", "_", href)

    img = tag.find("img")
    title = (img.get("alt") if img else None) or tag.get_text(strip=True)[:120] or "Tise-annonse"
    img_url = (img.get("src") or img.get("data-src")) if img else None

    return {
        "id": f"tise_{ad_id}",
        "source": "tise.com",
        "title": title,
        "price": "Se Tise",
        "url": url,
        "image_url": img_url,
        "description": "",
    }


def _find_items(data, depth: int = 0, max_depth: int = 9):
    if depth > max_depth:
        return None
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and any(
            k in first for k in ("id", "uuid", "title", "slug", "price")
        ):
            return data
    if isinstance(data, dict):
        for key in ("items", "listings", "products", "results", "hits", "data", "nodes", "edges"):
            if key in data:
                result = _find_items(data[key], depth + 1, max_depth)
                if result:
                    return result
        for value in data.values():
            if isinstance(value, (dict, list)):
                result = _find_items(value, depth + 1, max_depth)
                if result:
                    return result
    return None
