"""
Finn.no scraper.

Strategi:
  1. Hent søkeside som HTML.
  2. Prøv å lese __NEXT_DATA__ JSON (Next.js-bygg) – mest pålitelig.
  3. Fallback: BeautifulSoup HTML-parsing med flere CSS-selektorer.
"""

import json
import logging
import re
import time
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.finn.no/bap/forsale/search.html"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
}
_FINN_AD_RE  = re.compile(r"finnkode=(\d+)")
_FINN_ALT_RE = re.compile(r"/(\d{6,10})(?:[/?#]|$)")
# Ny URL-struktur (2026): /recommerce/forsale/item/{ID}
_FINN_NEW_RE = re.compile(r"/recommerce/forsale/item/(\d+)")


class FinnScraper:
    def __init__(self):
        # curl_cffi for bedre fingerprint (selv om Finn ikke blokkerer aktivt
        # nå, gir det robusthet hvis de skrur på beskyttelse).
        self.session = cf.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        params = {"q": keyword, "sort": "1"}  # sort=1 = nyeste først
        url = f"{_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        logger.debug("Finn.no søker: %s", url)

        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            logger.warning("Finn.no HTTP-feil for '%s': %s", keyword, exc)
            return []
        except requests.RequestException as exc:
            logger.error("Finn.no tilkoblingsfeil for '%s': %s", keyword, exc)
            return []

        ads = self._parse_next_data(resp.text)
        if not ads:
            ads = self._parse_html(resp.text)

        logger.info("Finn.no '%s': %d treff", keyword, len(ads))
        return ads

    # ── JSON-strategi ────────────────────────────────────────────────────

    def _parse_next_data(self, html: str) -> List[Dict]:
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("script", id="__NEXT_DATA__")
        if not tag or not tag.string:
            return []
        try:
            data = json.loads(tag.string)
        except json.JSONDecodeError:
            return []

        docs = _find_docs(data)
        if not docs:
            return []

        results = []
        for doc in docs:
            ad = self._doc_to_ad(doc)
            if ad:
                results.append(ad)
        return results

    def _doc_to_ad(self, doc: dict) -> Optional[Dict]:
        if not isinstance(doc, dict):
            return None

        # --- ID ---
        ad_id = str(
            doc.get("id") or
            doc.get("finnkode") or
            doc.get("ad_id") or
            ""
        )

        # --- Title ---
        title = (
            doc.get("heading") or
            doc.get("title") or
            doc.get("label") or
            ""
        )
        if not title:
            return None

        # --- URL ---
        raw_link = (
            doc.get("ad_link") or
            doc.get("canonical_url") or
            doc.get("url") or
            ""
        )
        if raw_link and not raw_link.startswith("http"):
            raw_link = "https://www.finn.no" + raw_link

        # Try to extract finnkode from link if id is missing
        if not ad_id and raw_link:
            m = _FINN_AD_RE.search(raw_link) or _FINN_ALT_RE.search(raw_link)
            if m:
                ad_id = m.group(1)

        if not ad_id:
            ad_id = raw_link  # worst-case: use URL as dedup key

        # --- Price ---
        price_raw = doc.get("price") or {}
        if isinstance(price_raw, dict):
            amount = price_raw.get("amount") or price_raw.get("value")
            currency = price_raw.get("currency_code") or price_raw.get("currency") or "kr"
            price = f"{amount} {currency}" if amount else "Pris ikke oppgitt"
        else:
            price = str(price_raw) if price_raw else "Pris ikke oppgitt"

        # --- Image ---
        img = doc.get("image") or doc.get("main_image") or {}
        if isinstance(img, dict):
            img_url = img.get("url") or img.get("src") or img.get("path")
        elif isinstance(img, str):
            img_url = img
        else:
            img_url = None

        # Ensure HTTPS
        if img_url and img_url.startswith("//"):
            img_url = "https:" + img_url

        # --- Description ---
        description = doc.get("description") or doc.get("body") or ""

        return {
            "id": ad_id,
            "source": "finn.no",
            "title": title,
            "price": price,
            "url": raw_link,
            "image_url": img_url,
            "description": description,
        }

    # ── HTML-fallback ────────────────────────────────────────────────────

    def _parse_html(self, html: str) -> List[Dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        seen_ids = set()

        # Finn.no 2026: <article class="sf-search-ad">. Eldre data-attributter
        # som data-id/data-finnkode finnes ikke lenger.
        articles = (
            soup.find_all("article", class_="sf-search-ad") or
            soup.find_all("article", attrs={"data-id": True}) or
            soup.find_all("article", attrs={"data-finnkode": True}) or
            soup.find_all("article")
        )

        for art in articles:
            ad = self._html_article_to_ad(art)
            if ad and ad["id"] not in seen_ids:
                seen_ids.add(ad["id"])
                results.append(ad)

        if not results:
            logger.debug("HTML-fallback: fant ingen <article>-elementer heller")
        return results

    def _html_article_to_ad(self, art) -> Optional[Dict]:
        ad_id = art.get("data-id") or art.get("data-finnkode") or ""

        # Foretrekk lenke som matcher /recommerce/forsale/item/{ID} – det er
        # den faktiske annonse-URL-en i moderne Finn. Andre <a> i kortet
        # peker til relaterte ting (selger, kategori osv.).
        link_tag = None
        for a in art.find_all("a", href=True):
            if _FINN_NEW_RE.search(a["href"]):
                link_tag = a
                break
        if not link_tag:
            link_tag = art.find("a", href=True)
        if not link_tag:
            return None
        href = link_tag["href"]
        if not href.startswith("http"):
            href = "https://www.finn.no" + href

        if not ad_id:
            m = (_FINN_NEW_RE.search(href) or
                 _FINN_AD_RE.search(href) or
                 _FINN_ALT_RE.search(href))
            ad_id = m.group(1) if m else href

        # Title – ofte h2/h3, men også sf-search-ad-link med tekst
        h2 = art.find(["h2", "h3"])
        title = h2.get_text(" ", strip=True) if h2 else ""
        if not title:
            sf_link = art.find(class_="sf-search-ad-link")
            if sf_link:
                title = sf_link.get_text(" ", strip=True)
        if not title:
            return None

        # Price – moderne Finn bruker nbsp før "kr": "1 500 kr"
        price = "Pris ikke oppgitt"
        price_tag = (art.find(class_=re.compile(r"price", re.I)) or
                     art.find(attrs={"data-testid": re.compile(r"price", re.I)}))
        if price_tag:
            price = price_tag.get_text(" ", strip=True)
        else:
            m = re.search(r'(\d[\d\s\xa0]*)\s*kr\b', art.get_text(" "))
            if m:
                price = m.group(0).strip()

        # Image
        img = art.find("img")
        img_url = None
        if img:
            img_url = (img.get("src") or img.get("data-src") or
                       img.get("data-lazy-src") or img.get("data-original"))
            if img_url and img_url.startswith("//"):
                img_url = "https:" + img_url

        # Description
        desc_tag = art.find("p")
        description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

        return {
            "id": str(ad_id),
            "source": "finn.no",
            "title": title,
            "price": price,
            "url": href,
            "image_url": img_url,
            "description": description,
        }


# ── Helpers ──────────────────────────────────────────────────────────────

def _find_docs(data, depth: int = 0, max_depth: int = 10):
    """Recursively find the first list that looks like ad docs."""
    if depth > max_depth:
        return None

    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and any(
            k in first for k in ("heading", "id", "ad_link", "canonical_url", "finnkode")
        ):
            return data

    if isinstance(data, dict):
        # Prioritised keys
        for key in ("docs", "results", "ads", "items", "listings", "hits"):
            if key in data:
                result = _find_docs(data[key], depth + 1, max_depth)
                if result:
                    return result
        for value in data.values():
            if isinstance(value, (dict, list)):
                result = _find_docs(value, depth + 1, max_depth)
                if result:
                    return result

    return None
