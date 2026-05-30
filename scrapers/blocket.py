"""
Blocket.se – Svensk markedsplass (Schibsted, samme HTML-plattform som Finn/DBA).
JSON-API-en ble blokkert; bruker nå HTML-parsing av søkesiden.
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE     = "https://www.blocket.se"
_SEARCH   = f"{_BASE}/annonser/hela_sverige"
_ITEM_RE  = re.compile(r"/recommerce/forsale/item/(\d+)")
_HEADERS  = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.5",
}


class BlocketScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_SEARCH}?{urllib.parse.urlencode({'q': keyword})}"
        try:
            resp = self.session.get(url, timeout=20, allow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Blocket feil for '%s': %s", keyword, exc)
            return []
        ads = _parse(resp.text)
        logger.info("Blocket '%s': %d treff", keyword, len(ads))
        return ads


def _parse(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    seen = set()
    for art in soup.find_all("article", class_="sf-search-ad"):
        ad = _article_to_ad(art)
        if ad and ad["id"] not in seen:
            seen.add(ad["id"])
            results.append(ad)
    return results


def _article_to_ad(art) -> Optional[Dict]:
    link = None
    for a in art.find_all("a", href=True):
        if _ITEM_RE.search(a["href"]):
            link = a
            break
    if not link:
        return None
    href = link["href"]
    if not href.startswith("http"):
        href = _BASE + href
    m = _ITEM_RE.search(href)
    if not m:
        return None
    ad_id = m.group(1)

    h = art.find(["h2", "h3"])
    title = h.get_text(" ", strip=True) if h else link.get_text(" ", strip=True)
    if not title:
        return None

    # Svenske priser: "1 500 kr"
    price = "Se pris (SEK)"
    m_p = re.search(r'(\d[\d\s\xa0]*)\s*kr\b', art.get_text(" "))
    if m_p:
        price = m_p.group(0).strip()

    img_tag = art.find("img")
    img_url = None
    if img_tag:
        img_url = img_tag.get("src") or img_tag.get("data-src")
        if img_url and img_url.startswith("//"):
            img_url = "https:" + img_url

    desc_tag = art.find("p")
    description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

    return {
        "id":          f"blocket_{ad_id}",
        "source":      "blocket.se",
        "title":       title,
        "price":       price,
        "url":         href,
        "image_url":   img_url,
        "description": description,
    }
