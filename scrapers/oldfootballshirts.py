"""
OldFootballShirts.com – stort arkiv/markedsplass for vintage fotballdrakter.
Har en dedikert Stabæk-side med HELE klubbhistorikken (inkl. gral-æraen
1990–2004). Siden boten kun bryr seg om Stabæk henter vi den ENE lag-siden
direkte og returnerer alle draktene – ny oppføring (f.eks. grønn arm) varsles.

Verifisert 2026-06-28: curl_cffi safari17_0 → 200, ~30+ Stabæk-drakter.
"""

import logging
import re
from typing import Dict, List

from bs4 import BeautifulSoup
from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE     = "https://www.oldfootballshirts.com"
# Fast Stabæk-lag-side (t477). Alt her ER Stabæk.
_TEAM_URL = f"{_BASE}/en/teams/s/stabaek-if/old-stabaek-if-football-shirts-t477.html"
_PROD_RE  = re.compile(r"-s(\d+)\.html")

_cache: List[Dict] = []


class OldFootballShirtsScraper:
    def __init__(self):
        self.client = cf.Session(impersonate="safari17_0", timeout=25)

    def search(self, keyword: str) -> List[Dict]:
        # Lag-siden er den samme uansett søkeord – hent og cache én gang.
        global _cache
        if not _cache:
            _cache = self._fetch()
        logger.info("OldFootballShirts '%s': %d treff", keyword, len(_cache))
        return _cache

    def _fetch(self) -> List[Dict]:
        try:
            r = self.client.get(_TEAM_URL)
            r.raise_for_status()
        except Exception as exc:
            logger.warning("OldFootballShirts feil: %s", exc)
            return []
        soup = BeautifulSoup(r.text, "lxml")
        ads, seen = [], set()
        for a in soup.select('a[href*="-s"][href*=".html"]'):
            href = a.get("href", "")
            m = _PROD_RE.search(href)
            if not m:
                continue
            pid = m.group(1)
            if pid in seen:
                continue
            seen.add(pid)
            txt = a.get_text(" ", strip=True)
            # Tittel uten årstall («???? Home») hoppes ikke over – «????» kan
            # være ukjent vintage-årgang. Prefiks med Stabæk så filteret treffer.
            title = f"Stabæk IF {txt}".strip()
            url = href if href.startswith("http") else _BASE + href
            img = a.select_one("img")
            isrc = (img.get("src") or img.get("data-src")) if img else None
            if isrc and isrc.startswith("/"):
                isrc = _BASE + isrc
            ads.append({
                "id":          f"ofs_{pid}",
                "source":      "oldfootballshirts.com",
                "title":       title[:200],
                "price":       "Se side (arkiv/salg)",
                "url":         url,
                "image_url":   isrc,
                "description": "",
            })
        return ads
