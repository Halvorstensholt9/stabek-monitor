"""
Catawiki – internasjonal auksjon for samlergjenstander inkl. fotballdrakter.
HTML-parsing av søkesiden (det interne API-et krever auth).
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE    = "https://www.catawiki.com"
_LOT_RE  = re.compile(r"/(?:en|nl|de|fr|it|es)/l/(\d+)")
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,no;q=0.8",
}


class CatawikiScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_BASE}/en/s?{urllib.parse.urlencode({'q': keyword})}"
        try:
            resp = self.session.get(url, timeout=20, allow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Catawiki feil for '%s': %s", keyword, exc)
            return []
        ads = _parse(resp.text)
        logger.info("Catawiki '%s': %d treff", keyword, len(ads))
        return ads


def _parse(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    seen = set()
    for card in soup.find_all("article", class_="c-lot-card__container"):
        ad = _card_to_ad(card)
        if ad and ad["id"] not in seen:
            seen.add(ad["id"])
            results.append(ad)
    return results


def _card_to_ad(card) -> Optional[Dict]:
    link = card.find("a", href=_LOT_RE)
    if not link:
        return None
    href = link["href"]
    if not href.startswith("http"):
        href = _BASE + href
    m = _LOT_RE.search(href)
    if not m:
        return None
    lot_id = m.group(1)

    # Tittel: kortet har én meningsfull tekstnode (lot-tittel)
    title = ""
    for t in card.stripped_strings:
        if len(t) > 5 and not t.isdigit():
            title = t
            break
    if not title:
        return None

    img = card.find("img")
    img_url = None
    if img:
        img_url = img.get("src") or img.get("data-src")
        if img_url and img_url.startswith("//"):
            img_url = "https:" + img_url

    return {
        "id":          f"cata_{lot_id}",
        "source":      "catawiki.com",
        "title":       title[:200],
        "price":       "Se Catawiki",
        "url":         href,
        "image_url":   img_url,
        "description": "",
    }
