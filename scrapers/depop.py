"""
Depop – Internasjonal second-hand plattform, populær blant draktsamlere.
API-en krever auth-token nå; bruker HTML-parsing av søkesiden i stedet.
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE     = "https://www.depop.com"
_PROD_RE  = re.compile(r"^/products/([^/?#]+)/?")
_PRICE_RE = re.compile(r"[£$€]\s?[\d,.]+|\b\d[\d,.]*\s?(?:USD|EUR|GBP|kr)\b", re.I)
_HEADERS  = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


class DepopScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_BASE}/search/?{urllib.parse.urlencode({'q': keyword})}"
        try:
            resp = self.session.get(url, timeout=20, allow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Depop feil for '%s': %s", keyword, exc)
            return []
        ads = _parse(resp.text)
        logger.info("Depop '%s': %d treff", keyword, len(ads))
        return ads


def _parse(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    seen = set()
    # Alle produkter ligger som <a href="/products/{slug}/"> inni <li>-elementer.
    for link in soup.find_all("a", href=_PROD_RE):
        ad = _link_to_ad(link)
        if ad and ad["id"] not in seen:
            seen.add(ad["id"])
            results.append(ad)
    return results


def _link_to_ad(link) -> Optional[Dict]:
    href = link.get("href", "")
    m = _PROD_RE.match(href)
    if not m:
        return None
    slug = m.group(1)
    url = _BASE + href

    # Container: nærmeste <li> eller <article>
    container = link.find_parent("li") or link.find_parent("article") or link.parent

    # Tittel: img alt har det vanligvis, men kan også være tom – bruk slug som fallback
    img = container.find("img") if container else None
    title = ""
    if img:
        title = (img.get("alt") or "").strip()
    if not title:
        title = slug.replace("-", " ").rsplit(" ", 1)[0]   # fjern hash-suffix

    img_url = None
    if img:
        img_url = img.get("src") or img.get("data-src")

    # Pris: tekstnode innenfor container som matcher pris-mønster
    price = "Se Depop"
    if container:
        text = container.get_text(" ", strip=True)
        m_p = _PRICE_RE.search(text)
        if m_p:
            price = m_p.group(0)

    return {
        "id":          f"depop_{slug}",
        "source":      "depop.com",
        "title":       title[:200],
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": "",
    }
