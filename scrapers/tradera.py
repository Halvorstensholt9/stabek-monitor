"""
Tradera.se – Svensk bruktmarkedsplass (som Finn.no).
Bruker HTML-parsing av søkeresultatsiden (API-et returnerer irrelevante treff).
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE    = "https://www.tradera.com"
_SEARCH  = f"{_BASE}/search"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,*/*;q=0.8",
    "Accept-Language": "sv-SE,sv;q=0.9,no;q=0.8,en;q=0.6",
}


class TraderaScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        params = {"q": keyword, "sortBy": "AddedOn_Desc"}
        url = f"{_SEARCH}?{urllib.parse.urlencode(params)}"
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Tradera feil for '%s': %s", keyword, exc)
            return []

        ads = _parse(resp.text, keyword)
        logger.info("Tradera '%s': %d treff", keyword, len(ads))
        return ads


def _parse(html: str, keyword: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []

    # Tradera bruker <article> eller <div> med data-item-id
    items = (
        soup.find_all("article", attrs={"data-item-id": True}) or
        soup.find_all("div", attrs={"data-item-id": True}) or
        soup.find_all("a", href=re.compile(r"/item/\d+/\d+/"))
    )

    for item in items:
        ad = _item_to_ad(item)
        if ad:
            # Kun behold treff som faktisk inneholder søkeordet
            kw_lower = keyword.lower().replace("æ", "a")
            title_lower = ad["title"].lower().replace("æ", "a")
            kw_parts = kw_lower.split()
            if kw_parts and kw_parts[0] not in title_lower:
                continue
            results.append(ad)

    return results


def _item_to_ad(item) -> Optional[Dict]:
    # Hvis item er en <a>-tag direkte
    if item.name == "a":
        href = item.get("href", "")
        url = (_BASE + href) if not href.startswith("http") else href
        m = re.search(r"/item/\d+/(\d+)/", href)
        ad_id = m.group(1) if m else href
        img = item.find("img")
        title = (img.get("alt") if img else None) or item.get_text(strip=True)[:120]
        img_url = (img.get("src") or img.get("data-src")) if img else None
        if not title:
            return None
        return {
            "id": f"tradera_{ad_id}",
            "source": "tradera.se",
            "title": title,
            "price": "Se bud",
            "url": url,
            "image_url": img_url,
            "description": "",
        }

    ad_id = str(item.get("data-item-id", ""))
    link = item.find("a", href=re.compile(r"/item/"))
    if not link:
        return None
    href = link["href"]
    url = (_BASE + href) if not href.startswith("http") else href

    if not ad_id:
        m = re.search(r"/item/\d+/(\d+)/", href)
        ad_id = m.group(1) if m else href

    title_tag = item.find(class_=re.compile(r"title|heading|name", re.I)) or item.find("h2") or item.find("h3")
    title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)[:120]
    if not title:
        return None

    price_tag = item.find(class_=re.compile(r"price|bid|amount", re.I))
    price = price_tag.get_text(strip=True) if price_tag else "Se bud"

    img = item.find("img")
    img_url = None
    if img:
        img_url = img.get("data-src") or img.get("src")
        if img_url and img_url.startswith("//"):
            img_url = "https:" + img_url

    return {
        "id": f"tradera_{ad_id}",
        "source": "tradera.se",
        "title": title,
        "price": price,
        "url": url,
        "image_url": img_url,
        "description": "",
    }
