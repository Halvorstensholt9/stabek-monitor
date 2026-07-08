"""
Subito.it – Italias største bruktmarked. Data ligger i __NEXT_DATA__ (Next.js):
props.pageProps.initialState.items.originalList. curl_cffi (Safari) omgår Cloudflare.
"""

import json
import logging
import re
import urllib.parse
from typing import Dict, List

from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_URL = "https://www.subito.it/annunci-italia/vendita/usato/"
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_LISTID = re.compile(r"list:(\d+)")


class SubitoScraper:
    def __init__(self):
        self.s = cf.Session(impersonate="safari17_0")

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_URL}?q={urllib.parse.quote(keyword)}"
        try:
            resp = self.s.get(url, timeout=20)
            m = _NEXT.search(resp.text)
            ads = (json.loads(m.group(1))["props"]["pageProps"]
                   ["initialState"]["items"]["originalList"])
        except Exception as exc:
            logger.warning("Subito feil for '%s': %s", keyword, exc)
            return []

        out = []
        for a in ads:
            urn = a.get("urn", "")
            mm = _LISTID.search(urn)
            aid = mm.group(1) if mm else urn
            title = (a.get("subject") or "").strip()
            u = (a.get("urls") or {}).get("default", "")
            if not aid or not title or not u:
                continue
            imgs = a.get("images") or []
            img = imgs[0].get("cdnBaseUrl") if imgs else None
            price = "Se Subito"
            p = (a.get("features") or {}).get("/price")
            if p and p.get("values"):
                price = (p["values"][0].get("value") or "Se Subito").strip()
            out.append({
                "id":          f"subito_{aid}",
                "source":      "subito.it",
                "title":       title[:200],
                "price":       price,
                "url":         u,
                "image_url":   img,
                "description": (a.get("body") or "")[:200],
            })
        logger.info("Subito '%s': %d treff", keyword, len(out))
        return out
