"""
Vintage Football Shirts – UK-spesialistside for vintage fotballdrakter.
Shopify-butikk: bruker JSON-søke-API.
URL: https://www.vintagefootballshirts.com
"""

import logging
import re
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE     = "https://www.vintagefootballshirts.com"
_JSON_API = f"{_BASE}/search.json"
_HEADERS  = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": _BASE + "/",
}


class VintageFCScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        ads = self._search_json(keyword)
        if ads is None:
            ads = self._search_html(keyword)
        logger.info("VintageFootballShirts '%s': %d treff", keyword, len(ads))
        return ads

    def _search_json(self, keyword: str) -> Optional[List[Dict]]:
        params = {"type": "product", "q": keyword}
        try:
            resp = self.session.get(_JSON_API, params=params, timeout=20)
            if resp.status_code in (403, 404, 429):
                return None
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return None

        products = (data.get("resources", {}).get("results", {}).get("products") or
                    data.get("results") or [])
        return [ad for ad in (_json_product(p) for p in products) if ad]

    def _search_html(self, keyword: str) -> List[Dict]:
        url = f"{_BASE}/search?{urllib.parse.urlencode({'q': keyword, 'type': 'product'})}"
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("VFS HTML-feil for '%s': %s", keyword, exc)
            return []
        return _parse_shopify_html(resp.text, _BASE, "vfs")


def _json_product(p: dict) -> Optional[Dict]:
    pid = str(p.get("id") or "")
    title = (p.get("title") or "").strip()
    if not pid or not title:
        return None

    handle = p.get("handle") or pid
    url = f"{_BASE}/products/{handle}"

    price_raw = p.get("price_min") or p.get("price") or ""
    try:
        price_str = f"£{int(price_raw) / 100:.2f}"
    except (ValueError, TypeError):
        price_str = str(price_raw) or "Se pris (£)"

    img = p.get("image") or (p.get("images") or [None])[0]
    img_url = (img.get("src") if isinstance(img, dict) else
               img if isinstance(img, str) else None)

    return {
        "id": f"vfs_{pid}",
        "source": "vintagefootballshirts.com",
        "title": title,
        "price": price_str,
        "url": url,
        "image_url": img_url,
        "description": "",
    }


def _parse_shopify_html(html: str, base: str, prefix: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    selectors = [
        ("div", re.compile(r"product[-_]card|grid[-_]product|product[-_]item", re.I)),
        ("li",  re.compile(r"product|grid__item", re.I)),
    ]
    products = []
    for tag, cls in selectors:
        products = soup.find_all(tag, class_=cls)
        if products:
            break
    for prod in products:
        link = prod.find("a", href=re.compile(r"/products/"))
        if not link:
            continue
        href = link["href"]
        url = (base + href) if not href.startswith("http") else href
        m = re.search(r"/products/([^/?#]+)", href)
        slug = m.group(1) if m else href
        title_tag = prod.find("h2") or prod.find("h3") or prod.find("h4")
        title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)[:120]
        if not title:
            continue
        price_tag = prod.find(class_=re.compile(r"price", re.I))
        price = price_tag.get_text(strip=True) if price_tag else "Se pris (£)"
        img = prod.find("img")
        img_url = None
        if img:
            src = img.get("data-src") or img.get("src") or ""
            img_url = ("https:" + src) if src.startswith("//") else (src or None)
        results.append({
            "id": f"{prefix}_{slug}",
            "source": f"{base.replace('https://www.', '')}",
            "title": title,
            "price": price,
            "url": url,
            "image_url": img_url,
            "description": "",
        })
    return results
