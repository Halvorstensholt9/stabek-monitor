"""
Grailed.com – internasjonalt bruktmarked for klær og drakter.
Bruker Grailed sitt Algolia-søke-API (public read-only nøkler).
"""

import logging
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_ALGOLIA_APP_ID   = "MNRWEFSS2Q"
_ALGOLIA_API_KEY  = "c89dbaddf15fe70e1941a109bf7c2a3d"
_ALGOLIA_INDEX    = "Listing_by_date_added_production"
_ALGOLIA_URL      = f"https://{_ALGOLIA_APP_ID.lower()}-dsn.algolia.net/1/indexes/{_ALGOLIA_INDEX}/query"

_HEADERS = {
    "X-Algolia-Application-Id": _ALGOLIA_APP_ID,
    "X-Algolia-API-Key":        _ALGOLIA_API_KEY,
    "Content-Type":             "application/json",
    "User-Agent":               "Mozilla/5.0 (compatible; DraktMonitor/1.0)",
}


class GrailedScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        payload = {
            "query":       keyword,
            "hitsPerPage": 40,
            "filters":     "sold=0",  # kun tilgjengelige listinger
        }
        try:
            resp = self.session.post(_ALGOLIA_URL, json=payload, timeout=20)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except Exception as exc:
            logger.debug("Grailed feil for '%s': %s", keyword, exc)
            return []

        ads = [a for a in (_hit_to_ad(h) for h in hits) if a]
        logger.info("Grailed '%s': %d treff", keyword, len(ads))
        return ads


def _hit_to_ad(h: dict) -> Optional[Dict]:
    listing_id = str(h.get("id") or h.get("objectID") or "")
    title      = (h.get("title") or "").strip()
    if not listing_id or not title:
        return None

    price_val = h.get("price")
    price     = f"${price_val}" if price_val is not None else "Se pris"

    url     = f"https://www.grailed.com/listings/{listing_id}"
    img_url = (h.get("cover_photo") or {}).get("image_url")

    location = h.get("location", "")
    designer = h.get("designer_names", "")
    desc     = f"{designer} – {location}".strip(" –")

    return {
        "id":          f"grailed_{listing_id}",
        "source":      "grailed.com",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": desc,
    }
