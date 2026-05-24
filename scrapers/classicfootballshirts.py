"""
Classic Football Shirts-scraper.
Britisk spesialistside for vintage fotballdrakter (Shopify-butikk).

Strategi:
  1. Shopify produktsøk-API (/search.json) – returnerer JSON, ikke blokkert
  2. Fallback: HTML-parsing av søkesiden
"""

import json
import logging
import re
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE_URL   = "https://www.classicfootballshirts.co.uk"
_JSON_API   = f"{_BASE_URL}/search.json"
_SEARCH_URL = f"{_BASE_URL}/search"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": _BASE_URL + "/",
}


class ClassicFCScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        ads = self._search_json(keyword)
        if ads is None:
            ads = self._search_html(keyword)
        logger.info("ClassicFootballShirts '%s': %d treff", keyword, len(ads))
        return ads

    # ── Shopify JSON API ─────────────────────────────────────────────────

    def _search_json(self, keyword: str) -> Optional[List[Dict]]:
        params = {"type": "product", "q": keyword}
        url = f"{_JSON_API}?{urllib.parse.urlencode(params)}"
        try:
            resp = self.session.get(url, timeout=20)
            if resp.status_code in (403, 429):
                logger.debug("CFS JSON-API blokkerte – prøver HTML")
                return None
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.debug("CFS JSON-API feil: %s – prøver HTML", exc)
            return None

        products = data.get("resources", {}).get("results", {}).get("products", [])
        if not products:
            # Noen Shopify-versjoner har en annen struktur
            products = data.get("results", [])

        return [ad for ad in (_json_product_to_ad(p) for p in products) if ad]

    # ── HTML-fallback ────────────────────────────────────────────────────

    def _search_html(self, keyword: str) -> List[Dict]:
        params = {"q": keyword, "type": "product"}
        url = f"{_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            logger.warning("CFS HTML HTTP-feil for '%s': %s", keyword, exc)
            return []
        except requests.RequestException as exc:
            logger.error("CFS HTML tilkoblingsfeil: %s", exc)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        selectors = [
            ("div", re.compile(r"product[-_]card|grid[-_]product|product[-_]item", re.I)),
            ("li",  re.compile(r"product[-_]card|grid[-_]product|grid__item", re.I)),
            ("article", re.compile(r"product", re.I)),
        ]
        products = []
        for tag, cls in selectors:
            products = soup.find_all(tag, class_=cls)
            if products:
                break

        for prod in products:
            ad = _html_product_to_ad(prod)
            if ad:
                results.append(ad)
        return results


# ── Helpers ──────────────────────────────────────────────────────────────

def _json_product_to_ad(p: dict) -> Optional[Dict]:
    pid = str(p.get("id") or "")
    title = (p.get("title") or "").strip()
    if not pid or not title:
        return None

    handle = p.get("handle") or pid
    url = f"{_BASE_URL}/products/{handle}"

    price_raw = p.get("price_min") or p.get("price") or p.get("variants", [{}])[0].get("price", "")
    if price_raw:
        try:
            price_str = f"£{int(price_raw) / 100:.2f}"
        except (ValueError, TypeError):
            price_str = str(price_raw)
    else:
        price_str = "Se pris (£)"

    img_url = None
    img = p.get("image") or (p.get("images") or [None])[0]
    if isinstance(img, dict):
        img_url = img.get("src") or img.get("url")
    elif isinstance(img, str) and img.startswith("http"):
        img_url = img

    return {
        "id": f"cfs_{pid}",
        "source": "classicfootballshirts.co.uk",
        "title": title,
        "price": price_str,
        "url": url,
        "image_url": img_url,
        "description": (p.get("body_html") and
                        BeautifulSoup(p["body_html"], "lxml").get_text(" ", strip=True)[:200]) or "",
    }


def _html_product_to_ad(prod) -> Optional[Dict]:
    link = prod.find("a", href=re.compile(r"/products/"))
    if not link:
        link = prod.find("a", href=True)
    if not link:
        return None

    href = link["href"]
    url = f"{_BASE_URL}{href}" if not href.startswith("http") else href
    m = re.search(r"/products/([^/?#]+)", href)
    slug = m.group(1) if m else re.sub(r"[^a-z0-9]", "_", href)

    title_tag = (
        prod.find(class_=re.compile(r"product.?title|card.?title", re.I)) or
        prod.find("h2") or prod.find("h3") or prod.find("h4")
    )
    title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)[:120]
    if not title:
        return None

    price_tag = prod.find(class_=re.compile(r"\bprice\b", re.I))
    price = re.sub(r"\s+", " ", price_tag.get_text(strip=True)).strip() if price_tag else "Se pris (£)"

    img = prod.find("img")
    img_url = None
    if img:
        src = img.get("data-src") or img.get("src") or img.get("srcset", "").split(" ")[0]
        if src and not src.startswith("data:"):
            img_url = ("https:" + src) if src.startswith("//") else src

    return {
        "id": f"cfs_{slug}",
        "source": "classicfootballshirts.co.uk",
        "title": title,
        "price": price,
        "url": url,
        "image_url": img_url,
        "description": "",
    }
