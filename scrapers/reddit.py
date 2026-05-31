"""
Reddit – søker i relevante fotball-subreddits etter Stabæk-drakter.
Bruker RSS-feed (search.rss). JSON-API blokkeres nå med 403, men
RSS slipper fortsatt gjennom (testet 2026-05-31).
"""

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE    = "https://www.reddit.com"
_HEADERS = {
    "User-Agent": "StabaekDraktMonitor/1.2 (vintage football shirt tracker; by stabaek-fan)",
}

# Søk i alle disse subredditsene samlet (+ betyr OR)
_SUBREDDIT_COMBO = (
    "footballjerseys+classicfootball+soccer_jerseys+"
    "SoccerJerseys+UKFootball+soccermarket"
)

_NS = {"atom": "http://www.w3.org/2005/Atom"}
_PRICE_RE = re.compile(
    r"(?:£|€|\$|kr|GBP|USD|EUR|NOK)\s*[\d,]+|[\d,]+\s*(?:kr|NOK|GBP|USD|EUR)",
    re.I,
)
_ID_RE = re.compile(r"/comments/([a-z0-9]+)/")


class RedditScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_BASE}/r/{_SUBREDDIT_COMBO}/search.rss"
        params = {
            "q":           keyword,
            "restrict_sr": "1",
            "sort":        "new",
            "limit":       25,
            "t":           "year",
        }
        try:
            full = f"{url}?{urllib.parse.urlencode(params)}"
            resp = self.session.get(full, timeout=25)
            resp.raise_for_status()
            # ET.fromstring trenger bytes for å håndtere XML-erklæringens encoding
            root = ET.fromstring(resp.content)
        except Exception as exc:
            logger.warning("Reddit feil for '%s': %s", keyword, exc)
            return []

        ads = []
        for entry in root.findall("atom:entry", _NS):
            ad = _entry_to_ad(entry)
            if ad:
                ads.append(ad)

        logger.info("Reddit '%s': %d treff", keyword, len(ads))
        return ads


def _entry_to_ad(entry) -> Optional[Dict]:
    def get(tag):
        el = entry.find(f"atom:{tag}", _NS)
        return el.text if el is not None and el.text else ""

    title = get("title").strip()
    if not title:
        return None

    # <link href="..." />
    link_el = entry.find("atom:link", _NS)
    url = link_el.get("href") if link_el is not None else ""
    if not url:
        return None

    m = _ID_RE.search(url)
    post_id = m.group(1) if m else url.rsplit("/", 1)[-1]

    # Sub-Reddit fra URL: /r/<name>/comments/...
    m_sub = re.search(r"/r/([a-zA-Z0-9_]+)/", url)
    subreddit = m_sub.group(1) if m_sub else "reddit"

    # Innhold i <content> er HTML i en <div> – plukk ut tekst og bilde
    content = get("content")
    description = ""
    img_url = None
    if content:
        # Plukk bilde fra første <img src="...">
        m_img = re.search(r'<img[^>]+src="([^"]+)"', content)
        if m_img:
            img_url = m_img.group(1).replace("&amp;", "&")
        # Strip HTML for tekst-snippet
        description = re.sub(r"<[^>]+>", " ", content)
        description = re.sub(r"\s+", " ", description).strip()[:300]

    # Pris fra tittel/beskrivelse
    price = "Se innlegg"
    m_p = _PRICE_RE.search(title + " " + description)
    if m_p:
        price = m_p.group(0).strip()

    return {
        "id":          f"reddit_{post_id}",
        "source":      f"reddit.com/r/{subreddit}",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": description,
    }
