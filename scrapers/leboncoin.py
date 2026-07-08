"""
Leboncoin.fr – Frankrikes store bruktmarked. Data i __NEXT_DATA__:
props.pageProps.searchData.ads. curl_cffi (Safari) for å omgå beskyttelse.
"""

import json
import logging
import re
import urllib.parse
from typing import Dict, List

from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_URL = "https://www.leboncoin.fr/recherche"
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class LeboncoinScraper:
    def __init__(self):
        self.s = cf.Session(impersonate="safari17_0")

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_URL}?text={urllib.parse.quote(keyword)}"
        try:
            resp = self.s.get(url, timeout=20)
            m = _NEXT.search(resp.text)
            ads = (json.loads(m.group(1))["props"]["pageProps"]
                   ["searchData"]["ads"])
        except Exception as exc:
            logger.warning("Leboncoin feil for '%s': %s", keyword, exc)
            return []

        out = []
        for a in ads:
            aid = str(a.get("list_id") or "")
            title = (a.get("subject") or "").strip()
            u = a.get("url") or ""
            if not aid or not title or not u:
                continue
            price = "Se pris (€)"
            pr = a.get("price")
            if isinstance(pr, list) and pr:
                price = f"{pr[0]} €"
            elif a.get("price_cents"):
                price = f"{int(a['price_cents'])/100:.0f} €"
            imgs = a.get("images") or {}
            img = None
            if isinstance(imgs, dict):
                img = imgs.get("thumb_url") or (imgs.get("urls") or [None])[0]
            out.append({
                "id":          f"leboncoin_{aid}",
                "source":      "leboncoin.fr",
                "title":       title[:200],
                "price":       price,
                "url":         u,
                "image_url":   img,
                "description": (a.get("body") or "")[:200],
            })
        logger.info("Leboncoin '%s': %d treff", keyword, len(out))
        return out
