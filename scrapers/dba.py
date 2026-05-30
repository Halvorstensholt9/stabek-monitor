"""
DBA.dk – Dansk markedsplass (Schibsted, samme HTML-plattform som Finn.no).
Bruker article.sf-search-ad + /recommerce/forsale/item/{ID}.
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE     = "https://www.dba.dk"
_ITEM_RE  = re.compile(r"/recommerce/forsale/item/(\d+)")
_HEADERS  = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "da-DK,da;q=0.9,no;q=0.8,en;q=0.6",
}


class DbaScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_BASE}/soeg/?soeg={urllib.parse.quote(keyword)}&sort=date"
        try:
            resp = self.session.get(url, timeout=20, allow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("DBA.dk feil for '%s': %s", keyword, exc)
            return []
        ads = _parse(resp.text)
        logger.info("DBA.dk '%s': %d treff", keyword, len(ads))
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
    # Velg lenken som peker til selve annonsen
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

    # DBA priser: "1.500 kr." (dansk skrivemåte)
    price = "Se pris (DKK)"
    m_p = re.search(r'(\d[\d.\s\xa0]*)\s*kr\.?', art.get_text(" "))
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
        "id":          f"dba_{ad_id}",
        "source":      "dba.dk",
        "title":       title,
        "price":       price,
        "url":         href,
        "image_url":   img_url,
        "description": description,
    }
