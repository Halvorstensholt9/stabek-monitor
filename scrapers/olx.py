"""
OLX.pl – stort bruktmarked (Polen/Øst-Europa). Bruker OLX' offentlige API
(/api/v1/offers/) som gir ren JSON. curl_cffi for robusthet.

Defensiv: enhver feil → returnerer [].
"""

import logging
import urllib.parse
from typing import Dict, List

from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_API = "https://www.olx.pl/api/v1/offers/"


class OLXScraper:
    def __init__(self):
        self.s = cf.Session(impersonate="safari17_0")

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_API}?query={urllib.parse.quote(keyword)}&limit=40"
        try:
            data = self.s.get(url, timeout=20).json().get("data", [])
        except Exception as exc:
            logger.warning("OLX feil for '%s': %s", keyword, exc)
            return []

        out = []
        for d in data:
            aid = str(d.get("id") or "")
            title = (d.get("title") or "").strip()
            u = d.get("url") or ""
            if not aid or not title or not u:
                continue
            price = "Se OLX"
            for p in d.get("params", []):
                if p.get("key") == "price":
                    v = p.get("value")
                    if isinstance(v, dict):
                        price = v.get("label") or f"{v.get('value','')} {v.get('currency','')}".strip()
                    break
            img = None
            photos = d.get("photos") or []
            if photos and photos[0].get("link"):
                img = (photos[0]["link"].replace("{width}", "640")
                       .replace("{height}", "480"))
            out.append({
                "id":          f"olx_{aid}",
                "source":      "olx.pl",
                "title":       title[:200],
                "price":       price,
                "url":         u,
                "image_url":   img,
                "description": (d.get("description") or "")[:200],
            })
        logger.info("OLX '%s': %d treff", keyword, len(out))
        return out
