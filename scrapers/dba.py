"""
DBA.dk – Dansk finn.no-ekvivalent (Den Blå Avis).
HTML-parsing av søkeresultater.
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE = "https://www.dba.dk"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,*/*;q=0.8",
    "Accept-Language": "da-DK,da;q=0.9,no;q=0.8,en;q=0.6",
}


class DbaScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_BASE}/soeg/?soeg={urllib.parse.quote(keyword)}&sort=date"
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("DBA.dk feil for '%s': %s", keyword, exc)
            return []

        ads = _parse(resp.text)
        logger.info("DBA.dk '%s': %d treff", keyword, len(ads))
        return ads


def _parse(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []

    # DBA bruker <article class="item-list__item"> eller <li class="listed-item">
    items = (
        soup.find_all("article", class_=re.compile(r"item", re.I)) or
        soup.find_all("li", class_=re.compile(r"listed-item|item-list", re.I)) or
        soup.find_all("div", class_=re.compile(r"result-item|listing-item", re.I))
    )

    for item in items:
        ad = _item_to_ad(item)
        if ad:
            results.append(ad)
    return results


def _item_to_ad(item) -> Optional[Dict]:
    link = item.find("a", href=re.compile(r"dba\.dk|^/"))
    if not link:
        link = item.find("a", href=True)
    if not link:
        return None

    href = link["href"]
    url = (_BASE + href) if not href.startswith("http") else href

    # ID fra URL
    m = re.search(r"/(\d{6,})", href)
    ad_id = m.group(1) if m else re.sub(r"[^a-z0-9]", "_", href)

    title_tag = (
        item.find(class_=re.compile(r"item-title|listing-title|headline", re.I)) or
        item.find("h2") or item.find("h3") or item.find("strong")
    )
    title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)[:120]
    if not title:
        return None

    price_tag = item.find(class_=re.compile(r"price", re.I))
    price = price_tag.get_text(strip=True) if price_tag else "Se pris (DKK)"

    img = item.find("img")
    img_url = None
    if img:
        img_url = img.get("data-src") or img.get("src")
        if img_url and img_url.startswith("//"):
            img_url = "https:" + img_url

    desc_tag = item.find(class_=re.compile(r"desc|body|text", re.I))
    description = desc_tag.get_text(strip=True) if desc_tag else ""

    return {
        "id": f"dba_{ad_id}",
        "source": "dba.dk",
        "title": title,
        "price": price,
        "url": url,
        "image_url": img_url,
        "description": description,
    }
