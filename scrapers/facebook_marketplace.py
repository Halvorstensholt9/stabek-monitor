"""
Facebook Marketplace – norsk bruktmarked, UTEN innlogging.

Facebook server-side-rendrer de FØRSTE søkeresultatene (typisk 4-8 stk)
i HTML-en før login-veggen. curl_cffi med Safari-fingerprint slipper
forbi bot-sjekken og leser disse direkte fra den embeddede JSON-en.

Bruker bynavn-slug «oslo» – for nisjesøk viser Marketplace treff fra
hele Norge uansett. Bilde ligger bak login, så image_url er None
(bildeanalyse hopper da over – tekst-filteret håndterer relevans).
"""

import logging
import re
import urllib.parse
from typing import Dict, List

from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_BASE   = "https://www.facebook.com"
_SEARCH = _BASE + "/marketplace/oslo/search/"
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.6",
}
_MARK = '"__isMarketplaceListingRenderable"'


class FacebookMarketplaceScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        url = f"{_SEARCH}?{urllib.parse.urlencode({'query': keyword})}"
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Facebook MP feil for '%s': %s", keyword, exc)
            return []
        ads = _parse(resp.text)
        logger.info("Facebook MP '%s': %d treff", keyword, len(ads))
        return ads


def _unescape(s: str) -> str:
    """Dekod \\uXXXX-escapede tegn (æ/ø/å) trygt til UTF-8."""
    try:
        return s.encode().decode("unicode_escape").encode("latin-1").decode("utf-8")
    except Exception:
        try:
            return s.encode().decode("unicode_escape")
        except Exception:
            return s


def _parse(html: str) -> List[Dict]:
    segments = html.split(_MARK)
    results, seen = [], set()

    for i in range(len(segments) - 1):
        # Listing-ID = siste lange tall-id i segmentet FØR markøren.
        ids = re.findall(r'"id":"(\d{8,})"', segments[i])
        if not ids:
            continue
        listing_id = ids[-1]
        if listing_id in seen:
            continue

        # Tittel/pris/by/solgt-status ligger like ETTER markøren.
        after = segments[i + 1][:900]
        title_m = re.search(r'"marketplace_listing_title":"([^"]+)"', after)
        if not title_m:
            continue
        price_m = re.search(r'"formatted_amount":"([^"]+)"', after)
        city_m  = re.search(r'"city":"([^"]+)"', after)
        if '"is_sold":true' in after:
            continue  # hopp over solgte

        seen.add(listing_id)
        title = _unescape(title_m.group(1))
        city  = _unescape(city_m.group(1)) if city_m else ""

        price = _unescape(price_m.group(1)).replace("\xa0", " ") if price_m else "Se FB"
        results.append({
            "id":          f"fb_{listing_id}",
            "source":      "facebook.com",
            "title":       title,
            "price":       price,
            "url":         f"{_BASE}/marketplace/item/{listing_id}",
            "image_url":   None,
            "description": f"Facebook Marketplace{' – ' + city if city else ''}",
        })

    return results
