"""
eBay scraper (ebay.co.uk og ebay.de).

Strategi:
  1. Prøv RSS-feed (XML) – vanskeligere å blokkere enn HTML-side
  2. Fallback: HTML-parsing med BeautifulSoup
"""

import logging
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_RSS_URLS = {
    "ebay.co.uk": "https://www.ebay.co.uk/sch/i.html",
    "ebay.de":    "https://www.ebay.de/sch/i.html",
    "ebay.com":   "https://www.ebay.com/sch/i.html",
    "ebay.fr":    "https://www.ebay.fr/sch/i.html",
    "ebay.nl":    "https://www.ebay.nl/sch/i.html",
}

_HEADERS_RSS = {
    "User-Agent": "Mozilla/5.0 (compatible; RSS reader)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

_HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

_ITEM_ID_RE = re.compile(r"/itm/(?:[^/]+/)?(\d+)")
_NS = {"": "http://www.w3.org/2005/Atom", "atom": "http://www.w3.org/2005/Atom"}


class EbayScraper:
    def __init__(self):
        self.rss_session  = requests.Session()
        self.html_session = requests.Session()
        self.rss_session.headers.update(_HEADERS_RSS)
        self.html_session.headers.update(_HEADERS_HTML)

    def search(self, keyword: str) -> List[Dict]:
        """Søker alle 5 eBay-markeder parallelt for ett søkeord."""
        results = []

        def _search_one(site_key, base_url):
            ads = self._search_rss(keyword, site_key, base_url)
            if ads is None:
                ads = self._search_html(keyword, site_key, base_url)
            logger.info("eBay %s '%s': %d treff", site_key, keyword, len(ads))
            return ads

        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="ebay") as pool:
            futures = {
                pool.submit(_search_one, sk, bu): sk
                for sk, bu in _RSS_URLS.items()
            }
            for future in as_completed(futures):
                try:
                    results.extend(future.result())
                except Exception as exc:
                    logger.warning("eBay %s feil: %s", futures[future], exc)

        return results

    # ── RSS ──────────────────────────────────────────────────────────────

    def _search_rss(self, keyword: str, site_key: str, base_url: str) -> Optional[List[Dict]]:
        params = {
            "_nkw": keyword,
            "_sop": "10",            # nyeste først
            "LH_ItemCondition": "3000",  # brukt
            "_rss": "1",             # be om RSS
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        try:
            resp = self.rss_session.get(url, timeout=20)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            if "xml" not in content_type and not resp.text.strip().startswith("<"):
                # Fikk HTML i stedet – fallback
                return None
            return self._parse_rss(resp.text, site_key)
        except requests.HTTPError as exc:
            logger.debug("eBay RSS %s HTTP-feil: %s", site_key, exc)
            return None
        except requests.RequestException as exc:
            logger.debug("eBay RSS %s tilkoblingsfeil: %s", site_key, exc)
            return None

    def _parse_rss(self, xml_text: str, source: str) -> List[Dict]:
        ads = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.debug("eBay RSS XML-parsefeil: %s", exc)
            return []

        # RSS 2.0
        for item in root.findall(".//item"):
            ad = self._rss_item_to_ad(item, source)
            if ad:
                ads.append(ad)

        # Atom (eBay bruker noen ganger dette)
        if not ads:
            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                ad = self._atom_entry_to_ad(entry, source)
                if ad:
                    ads.append(ad)

        return ads

    def _rss_item_to_ad(self, item, source: str) -> Optional[Dict]:
        title = _text(item, "title") or ""
        link  = _text(item, "link") or ""
        desc  = _text(item, "description") or ""

        if not title or not link:
            return None

        m = _ITEM_ID_RE.search(link)
        ad_id = m.group(1) if m else link

        # Pris fra beskrivelse: "Current price: £35.00"
        price = _extract_price_from_text(desc) or "Se eBay"

        # Bilde fra <description> HTML
        img_url = _extract_img_from_html(desc)

        return {
            "id": ad_id,
            "source": source,
            "title": title[:200],
            "price": price,
            "url": link,
            "image_url": img_url,
            "description": BeautifulSoup(desc, "lxml").get_text(" ", strip=True)[:300],
        }

    def _atom_entry_to_ad(self, entry, source: str) -> Optional[Dict]:
        ns = "http://www.w3.org/2005/Atom"
        title = entry.findtext(f"{{{ns}}}title") or ""
        link_el = entry.find(f"{{{ns}}}link[@rel='alternate']")
        link = link_el.get("href", "") if link_el is not None else ""
        if not title or not link:
            return None
        m = _ITEM_ID_RE.search(link)
        ad_id = m.group(1) if m else link
        return {
            "id": ad_id,
            "source": source,
            "title": title[:200],
            "price": "Se eBay",
            "url": link,
            "image_url": None,
            "description": "",
        }

    # ── HTML-fallback ────────────────────────────────────────────────────

    def _search_html(self, keyword: str, site_key: str, base_url: str) -> List[Dict]:
        params = {
            "_nkw": keyword,
            "_sop": "10",
            "LH_ItemCondition": "3000",
            "_ipg": "60",
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        try:
            resp = self.html_session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            logger.warning("eBay HTML %s HTTP-feil for '%s': %s", site_key, keyword, exc)
            return []
        except requests.RequestException as exc:
            logger.error("eBay HTML %s tilkoblingsfeil: %s", site_key, exc)
            return []
        return self._parse_html(resp.text, site_key)

    def _parse_html(self, html: str, source: str) -> List[Dict]:
        soup = BeautifulSoup(html, "lxml")
        ads = []
        for item in soup.select("li.s-item"):
            ad = self._html_item_to_ad(item, source)
            if ad:
                ads.append(ad)
        return ads

    def _html_item_to_ad(self, item, source: str) -> Optional[Dict]:
        title_tag = item.select_one(".s-item__title")
        if not title_tag:
            return None
        title = title_tag.get_text(strip=True)
        if title.lower() in ("shop on ebay", "results matching fewer words"):
            return None

        link_tag = item.select_one("a.s-item__link")
        url = link_tag["href"] if link_tag else ""
        m = _ITEM_ID_RE.search(url)
        ad_id = m.group(1) if m else url
        if not ad_id:
            return None

        price_tag = item.select_one(".s-item__price")
        price = price_tag.get_text(strip=True) if price_tag else "Se eBay"

        img_tag = item.select_one(".s-item__image-wrapper img, .s-item__image img")
        img_url = None
        if img_tag:
            img_url = img_tag.get("data-src") or img_tag.get("src") or ""
            img_url = re.sub(r"s-l\d+\.(jpg|webp|png)", r"s-l500.\1", img_url) or None

        sub_tag = item.select_one(".s-item__subtitle, .s-item__condition")
        description = sub_tag.get_text(strip=True) if sub_tag else ""

        return {
            "id": ad_id,
            "source": source,
            "title": title,
            "price": price,
            "url": url,
            "image_url": img_url,
            "description": description,
        }


# ── Helpers ──────────────────────────────────────────────────────────────

def _text(element, tag: str) -> Optional[str]:
    child = element.find(tag)
    return child.text.strip() if child is not None and child.text else None


_PRICE_RE = re.compile(r"(?:£|€|\$|kr)\s*([\d,. ]+)|(\d[\d,.]*)\s*(?:£|€|\$|kr)", re.I)


def _extract_price_from_text(html_or_text: str) -> Optional[str]:
    text = BeautifulSoup(html_or_text, "lxml").get_text(" ") if "<" in html_or_text else html_or_text
    m = _PRICE_RE.search(text)
    return m.group(0).strip() if m else None


def _extract_img_from_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "lxml")
    img = soup.find("img")
    if not img:
        return None
    src = img.get("src") or img.get("data-src") or ""
    return src if src.startswith("http") else None
