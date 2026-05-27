"""
The Football Idiots (thefootballidiots.com) – britisk vintage-draktbutikk.
Bruker Shopify JSON-søk som primær, HTML som fallback.
"""

import logging
import re
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE    = "https://www.thefootballidiots.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*;q=0.8",
}


class FootballIdiotsScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        ads, shopify_ok = self._search_shopify(keyword)
        if not shopify_ok:
            # Shopify-API feilet helt – prøv HTML
            ads = self._search_html(keyword)
        logger.info("FootballIdiots '%s': %d treff", keyword, len(ads))
        return ads

    # ── Shopify JSON API ──────────────────────────────────────────────────
    def _search_shopify(self, keyword: str):
        """Returnerer (liste, api_svarte: bool)."""
        url    = f"{_BASE}/search.json"
        params = {"q": keyword, "type": "product", "limit": 50}
        try:
            resp = self.session.get(url, params=params, timeout=20)
            if resp.status_code not in (200, 206):
                return [], False
            data = resp.json()
        except Exception:
            return [], False

        items = data.get("results") or data.get("products") or []
        return [a for a in (_shopify_to_ad(p) for p in items) if a], True

    # ── HTML fallback ─────────────────────────────────────────────────────
    def _search_html(self, keyword: str) -> List[Dict]:
        url    = f"{_BASE}/search"
        params = {"q": keyword, "type": "product"}
        try:
            resp = self.session.get(url, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as exc:
            logger.debug("FootballIdiots HTML feil for '%s': %s", keyword, exc)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        return [
            a for a in (
                _html_to_ad(item)
                for item in soup.select(
                    "li.product-item, div.product-item, "
                    ".grid__item, article.product-card, "
                    "[class*='ProductCard'], [class*='product-card']"
                )
            )
            if a
        ]


def _shopify_to_ad(p: dict) -> Optional[Dict]:
    pid   = str(p.get("id", ""))
    title = (p.get("title") or "").strip()
    if not title:
        return None

    handle = p.get("handle") or pid
    url    = f"{_BASE}/products/{handle}"

    # Pris fra første variant
    price_cents = None
    variants    = p.get("variants") or []
    if variants:
        price_cents = variants[0].get("price")
    if price_cents is None:
        price_cents = p.get("price_min") or p.get("price")
    if price_cents is not None:
        try:
            price = f"£{int(price_cents) / 100:.0f}"
        except (ValueError, TypeError):
            price = str(price_cents)
    else:
        price = "Se pris"

    imgs    = p.get("images") or []
    img_url = imgs[0].get("src") if imgs else None

    return {
        "id":          f"tfi_{pid}",
        "source":      "thefootballidiots.com",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": (p.get("body_html") or "")[:200],
    }


def _html_to_ad(item) -> Optional[Dict]:
    link = item.find("a", href=re.compile(r"/products/"))
    if not link:
        return None

    href = link.get("href", "")
    url  = (_BASE + href) if not href.startswith("http") else href

    m      = re.search(r"/products/([^/?#]+)", href)
    handle = m.group(1) if m else re.sub(r"[^\w-]", "_", href)[:40]

    title_tag = (
        item.find(class_=re.compile(r"title|name", re.I)) or
        item.find("h2") or item.find("h3")
    )
    title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)[:100]
    if not title:
        return None

    price_tag = item.find(class_=re.compile(r"price", re.I))
    price     = price_tag.get_text(strip=True) if price_tag else "Se pris"

    img     = item.find("img")
    img_url = None
    if img:
        img_url = img.get("src") or img.get("data-src")

    return {
        "id":          f"tfi_{handle}",
        "source":      "thefootballidiots.com",
        "title":       title,
        "price":       price,
        "url":         url,
        "image_url":   img_url,
        "description": "",
    }
