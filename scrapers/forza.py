"""
Forzasecondhand.no-scraper.
Norsk spesialistside for brukte fotballdrakter (WooCommerce).
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE_URL = "https://forzasecondhand.no"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "nb-NO,nb;q=0.9",
}


class ForzaScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        params = {"s": keyword, "post_type": "product"}
        url = f"{_BASE_URL}/?{urllib.parse.urlencode(params)}"
        logger.debug("Forzasecondhand søker: %s", url)

        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Forzasecondhand feil for '%s': %s", keyword, exc)
            return []

        ads = self._parse(resp.text)
        logger.info("Forzasecondhand '%s': %d treff", keyword, len(ads))
        return ads

    def _parse(self, html: str) -> List[Dict]:
        soup = BeautifulSoup(html, "lxml")

        # WooCommerce bruker <li class="product ..."> eller <div class="product ...">
        products = (
            soup.find_all("li", class_=re.compile(r"\bproduct\b")) or
            soup.find_all("div", class_=re.compile(r"product-small|product-grid-item|wc-block-grid__product"))
        )

        results = []
        for prod in products:
            ad = self._product_to_ad(prod)
            if ad:
                results.append(ad)
        return results

    def _product_to_ad(self, prod) -> Optional[Dict]:
        link = prod.find("a", href=re.compile(r"forzasecondhand\.no|^/"))
        if not link:
            link = prod.find("a", href=True)
        if not link:
            return None

        url = link["href"]
        if not url.startswith("http"):
            url = _BASE_URL + url

        slug = url.rstrip("/").split("/")[-1]
        ad_id = f"forza_{slug}"

        # Tittel
        title_tag = (
            prod.find(class_=re.compile(r"woocommerce-loop-product__title|product.?title", re.I)) or
            prod.find("h2") or prod.find("h3") or prod.find("h4")
        )
        title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)[:120]
        if not title:
            return None

        # Pris
        price_tag = prod.find(class_=re.compile(r"\bprice\b", re.I))
        price = price_tag.get_text(strip=True) if price_tag else "Se pris"
        # Fjern HTML-artefakter
        price = re.sub(r"\s+", " ", price).strip()

        # Bilde
        img = prod.find("img")
        img_url = None
        if img:
            img_url = img.get("data-src") or img.get("src") or img.get("data-lazy-src")
            if img_url and img_url.startswith("data:"):
                img_url = None  # base64-placeholder

        return {
            "id": ad_id,
            "source": "forzasecondhand.no",
            "title": title,
            "price": price,
            "url": url,
            "image_url": img_url,
            "description": "",
        }
