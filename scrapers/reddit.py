"""
Reddit – søker i relevante fotball-subreddits etter Stabæk-drakter.
Bruker Reddits offentlige JSON-API (ingen innlogging nødvendig).
"""

import logging
import re
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_BASE    = "https://www.reddit.com"
_HEADERS = {
    # Reddit krever en ikke-tom User-Agent
    "User-Agent": "StabaekDraktMonitor/1.1 (vintage football shirt tracker; by stabæk-fan)",
    "Accept": "application/json",
}

# Søk i alle disse subredditsene samlet (+ betyr OR)
_SUBREDDIT_COMBO = "footballjerseys+classicfootball+soccer_jerseys+SoccerJerseys+UKFootball+soccermarket"


class RedditScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        url    = f"{_BASE}/r/{_SUBREDDIT_COMBO}/search.json"
        params = {
            "q":           keyword,
            "restrict_sr": "1",
            "sort":        "new",
            "limit":       25,
            "t":           "year",   # siste år
        }
        try:
            resp = self.session.get(url, params=params, timeout=25)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("Reddit feil for '%s': %s", keyword, exc)
            return []

        posts = data.get("data", {}).get("children", [])
        ads   = []
        for post in posts:
            ad = _post_to_ad(post.get("data", {}))
            if ad:
                ads.append(ad)

        logger.info("Reddit '%s': %d treff", keyword, len(ads))
        return ads


def _post_to_ad(p: dict) -> Optional[Dict]:
    post_id = p.get("id", "")
    title   = p.get("title", "").strip()
    if not post_id or not title:
        return None

    permalink = p.get("permalink", "")
    url       = (_BASE + permalink).rstrip("/") if permalink else _BASE
    subreddit = p.get("subreddit", "")

    # Tekst / beskrivelse
    selftext    = p.get("selftext", "")[:300]
    description = selftext if selftext and selftext != "[removed]" else ""

    # Prøv å plukke ut pris fra tittel/tekst
    price  = "Se innlegg"
    pm     = re.search(
        r"(?:£|€|\$|kr|GBP|USD|EUR|NOK)\s*[\d,]+|[\d,]+\s*(?:kr|NOK|GBP|USD|EUR)",
        title + " " + selftext, re.I,
    )
    if pm:
        price = pm.group(0).strip()

    # Bilde (Reddit returnerer HTML-escaped URL-er)
    img_url = None
    preview = p.get("preview", {})
    images  = preview.get("images", [])
    if images:
        src     = images[0].get("source", {})
        img_url = src.get("url", "").replace("&amp;", "&")
    if not img_url and p.get("thumbnail", "").startswith("http"):
        img_url = p["thumbnail"]

    flair = p.get("link_flair_text") or ""
    desc  = f"[{flair}] {description}".strip("[] ") if flair else description

    return {
        "id":          f"reddit_{post_id}",
        "source":      f"reddit.com/r/{subreddit}",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": desc,
    }
