"""
Generelt websøk via DuckDuckGo HTML.

Brukes for å fange opp små sider/markedsplasser som ikke har sin egen
scraper – fora, små nettbutikker, blogger, sociale medier osv.

Strategi:
  - Søker via html.duckduckgo.com (ingen API-nøkkel nødvendig)
  - Filtrerer bort domener vi allerede har egne skrapere for
    (unngår duplikater)
  - Filtrerer bort åpenbart irrelevante domener (Wikipedia, nyheter osv.)
  - Returnerer titler + URL-er som «annonser» – filteret rydder resten
"""

import logging
import re
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,no;q=0.8",
}

# Domener vi allerede skraper – hopp over (unngå duplikater)
_OWN_DOMAINS = {
    "finn.no", "tise.com", "forzasecondhand.no", "draktgata.no",
    "ebay.co.uk", "ebay.de", "ebay.com", "ebay.nl", "ebay.fr",
    "vinted.com", "vinted.no", "vinted.de", "vinted.co.uk",
    "tradera.com", "blocket.se", "dba.dk", "depop.com",
    "classicfootballshirts.co.uk", "vintagefootballshirts.com",
    "reddit.com", "old.reddit.com",
    "catawiki.com", "thefootballidiots.com",
    "marktplaats.nl", "grailed.com", "cultkits.com",
    "classickits.no", "532.no",
}

# Domener som åpenbart ikke selger drakter (nyheter, oppslagsverk, sosialt)
_BLOCKED_DOMAINS = {
    "wikipedia.org", "no.wikipedia.org", "en.wikipedia.org",
    "stabak.no", "stabakbutikken.no",          # offisielle, kun moderne
    "unisportstore.no", "antonsport.no",       # kun moderne nye drakter
    "youtube.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "vg.no", "dagbladet.no", "nrk.no", "tv2.no", "aftenposten.no",
    "transfermarkt.com", "soccerway.com", "fbref.com", "uefa.com",
    "amazon.com", "amazon.co.uk", "amazon.de",
    "google.com", "duckduckgo.com", "bing.com",
    "grokipedia.com", "footballwiki.com",
    "github.com", "githubusercontent.com",     # vårt eget repo
    "espn.com", "espnfc.com", "skysports.com", "bbc.com", "bbc.co.uk",
    "linkedin.com", "tiktok.com", "pinterest.com",
}


class WebSearchScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        try:
            r = self.session.get(_DDG_URL, params={"q": keyword}, timeout=20)
            r.raise_for_status()
        except Exception as exc:
            logger.warning("WebSearch feil for '%s': %s", keyword, exc)
            return []

        soup = BeautifulSoup(r.text, "lxml")
        ads = []
        seen_urls = set()
        for result in soup.select("div.result, div.web-result"):
            ad = self._result_to_ad(result, seen_urls)
            if ad:
                ads.append(ad)
        logger.info("WebSearch '%s': %d treff", keyword, len(ads))
        return ads

    def _result_to_ad(self, result, seen_urls) -> Optional[Dict]:
        link = result.select_one("a.result__a, a.result-link")
        if not link:
            return None
        href = link.get("href", "")
        # DDG bruker redirect-URLer: /l/?uddg=ENCODED_URL
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            href = unquote(m.group(1))
        if not href.startswith("http"):
            return None

        try:
            host = urlparse(href).netloc.lower().lstrip("www.")
        except Exception:
            return None

        # Hopp over egne domener (dobbel-dekning) og blokkerte
        for blocked in _OWN_DOMAINS | _BLOCKED_DOMAINS:
            if host == blocked or host.endswith("." + blocked):
                return None

        if href in seen_urls:
            return None
        seen_urls.add(href)

        title = link.get_text(" ", strip=True)
        if not title:
            return None

        snippet_el = result.select_one(".result__snippet, .result-snippet")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

        # Unik ID basert på URL
        ad_id = "web_" + re.sub(r"[^a-z0-9]+", "_", href.lower())[:80]

        return {
            "id":          ad_id,
            "source":      f"web:{host}",
            "title":       title[:200],
            "price":       "Se nettsiden",
            "url":         href,
            "image_url":   None,
            "description": snippet[:300],
        }
