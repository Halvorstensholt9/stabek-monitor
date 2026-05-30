"""
ClassicFootballShirts.co.uk – britisk vintage-spesialist.
Magento-katalog: /catalogsearch/result/?q=...
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE     = "https://www.classicfootballshirts.co.uk"
_SEARCH   = f"{_BASE}/catalogsearch/result/"
_PROD_RE  = re.compile(r"/([a-z0-9-]+)\.html$")
_PRICE_RE = re.compile(r"£\s?[\d,.]+")
_HEADERS  = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


class ClassicFCScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_SEARCH}?{urllib.parse.urlencode({'q': keyword})}"
        try:
            resp = self.session.get(url, timeout=20, allow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("ClassicFootballShirts feil for '%s': %s", keyword, exc)
            return []
        ads = _parse(resp.text)
        logger.info("ClassicFootballShirts '%s': %d treff", keyword, len(ads))
        return ads


def _parse(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    seen = set()
    for item in soup.find_all("div", class_="product-item"):
        ad = _item_to_ad(item)
        if ad and ad["id"] not in seen:
            seen.add(ad["id"])
            results.append(ad)
    return results


def _item_to_ad(item) -> Optional[Dict]:
    # CFS-lenker ender på .html og inneholder produkt-slug + SKU
    link = item.find("a", href=_PROD_RE)
    if not link:
        link = item.find("a", href=True)
    if not link:
        return None
    href = link["href"]
    if not href.startswith("http"):
        href = _BASE + href
    m = _PROD_RE.search(href)
    if not m:
        return None
    slug = m.group(1)

    # Tittel: lenke-tekst eller img alt
    title = link.get_text(" ", strip=True)
    if not title or len(title) < 5:
        img = item.find("img")
        if img:
            title = (img.get("alt") or "").strip()
    if not title:
        return None
    # CFS legger ofte "Condition: Mint" osv. på slutten – behold den, filteret klarer det
    title = re.sub(r"\s+", " ", title)[:200]

    # Pris
    price = "Se CFS (GBP)"
    text = item.get_text(" ", strip=True)
    m_p = _PRICE_RE.search(text)
    if m_p:
        price = m_p.group(0).replace(" ", "")

    img_tag = item.find("img")
    img_url = None
    if img_tag:
        img_url = img_tag.get("src") or img_tag.get("data-src")
        if img_url and img_url.startswith("//"):
            img_url = "https:" + img_url

    return {
        "id":          f"cfs_{slug}",
        "source":      "classicfootballshirts.co.uk",
        "title":       title,
        "price":       price,
        "url":         href,
        "image_url":   img_url,
        "description": "",
    }
