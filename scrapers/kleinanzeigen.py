"""
Kleinanzeigen.de – Tysklands største bruktmarkedsplass (tidl. eBay
Kleinanzeigen). Tyske samlere har Stabæk-drakter fra europacup-kamper.
HTML-parsing av søkeresultater via curl_cffi + Safari-fingerprint.
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE   = "https://www.kleinanzeigen.de"
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
}


class KleinanzeigenScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        # Kleinanzeigen bruker /s-<søkeord>/k0 for fritekstsøk
        slug = urllib.parse.quote(keyword.lower().replace(" ", "-"))
        url = f"{_BASE}/s-{slug}/k0"
        try:
            resp = self.session.get(url, timeout=20, allow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Kleinanzeigen feil for '%s': %s", keyword, exc)
            return []
        ads = _parse(resp.text)
        logger.info("Kleinanzeigen '%s': %d treff", keyword, len(ads))
        return ads


def _parse(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results, seen = [], set()
    for art in soup.select("article.aditem"):
        ad = _article_to_ad(art)
        if ad and ad["id"] not in seen:
            seen.add(ad["id"])
            results.append(ad)
    return results


def _article_to_ad(art) -> Optional[Dict]:
    ad_id = art.get("data-adid")
    link = art.select_one("a[href]")
    if not link:
        return None
    href = link.get("href", "")
    if not href.startswith("http"):
        href = _BASE + href
    if not ad_id:
        m = re.search(r"/(\d{6,})(?:[/?-]|$)", href)
        ad_id = m.group(1) if m else href

    title_tag = art.select_one("h2 a, .text-module-begin a, a.ellipsis")
    title = title_tag.get_text(" ", strip=True) if title_tag else link.get_text(" ", strip=True)
    if not title:
        return None

    price_tag = art.select_one(
        ".aditem-main--middle--price-shipping--price, .aditem-details strong, [class*=price]"
    )
    price = price_tag.get_text(" ", strip=True) if price_tag else "Se pris (EUR)"

    img_tag = art.select_one("img")
    img_url = None
    if img_tag:
        img_url = img_tag.get("src") or img_tag.get("data-imgsrc")

    desc_tag = art.select_one(".aditem-main--middle--description, p")
    description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

    return {
        "id":          f"kleinanz_{ad_id}",
        "source":      "kleinanzeigen.de",
        "title":       title,
        "price":       price,
        "url":         href,
        "image_url":   img_url,
        "description": description[:300],
    }
