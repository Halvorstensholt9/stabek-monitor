"""
Poshmark (USA) – stort bruktmarked. Data ligger i window.__INITIAL_STATE__
under $_search.gridData.data. curl_cffi for robusthet.

Defensiv: enhver feil → returnerer [].
"""

import json
import logging
import urllib.parse
from typing import Dict, List

from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_URL = "https://poshmark.com/search"


def _extract_state(html: str):
    """Hent ut det balanserte __INITIAL_STATE__-JSON-objektet."""
    i = html.find("__INITIAL_STATE__")
    if i < 0:
        return None
    st = html.find("{", i)
    if st < 0:
        return None
    depth = 0
    for j in range(st, len(html)):
        c = html[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[st:j + 1])
    return None


class PoshmarkScraper:
    def __init__(self):
        self.s = cf.Session(impersonate="safari17_0")

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_URL}?query={urllib.parse.quote(keyword)}"
        try:
            state = _extract_state(self.s.get(url, timeout=20).text)
            posts = state["$_search"]["gridData"]["data"]
        except Exception as exc:
            logger.warning("Poshmark feil for '%s': %s", keyword, exc)
            return []

        out = []
        for p in posts:
            aid = str(p.get("id") or "")
            title = (p.get("title") or "").strip()
            if not aid or not title:
                continue
            price = "Se Poshmark"
            pa = p.get("price_amount")
            if isinstance(pa, dict):
                price = f"{pa.get('currency_symbol','$')}{pa.get('val','')}".strip()
            elif p.get("price"):
                price = f"${p['price']}"
            cs = p.get("cover_shot") or {}
            img = cs.get("url") or cs.get("url_small")
            out.append({
                "id":          f"poshmark_{aid}",
                "source":      "poshmark.com",
                "title":       title[:200],
                "price":       price,
                "url":         f"https://poshmark.com/listing/{aid}",
                "image_url":   img,
                "description": "",
            })
        logger.info("Poshmark '%s': %d treff", keyword, len(out))
        return out
