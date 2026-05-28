#!/usr/bin/env python3
"""
Dybdesøk + statistikkrapport for Stabæk Drakt Monitor.

Kjøres periodisk (~hvert 3. time) ved siden av standard-monitoren.
Gjør ting monitoren IKKE gjør:
  1. eBay solgte/fullførte annonser  – historikk, avslørte drakter som dukket opp
  2. Bredere søk uten "stabæk" i tittel – grønn arm norsk fotball o.l.
  3. Reddit siste innlegg (live søk)
  4. Statistikkrapport sendt til Telegram

Bruk: python3 deep_scan.py
"""

import logging
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import requests
import yaml
from bs4 import BeautifulSoup

from database import Database
from notifier import Telegram

logger = logging.getLogger("deep_scan")

# ── Konfig ───────────────────────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,no;q=0.8",
}

# ── eBay solgte/fullførte annonser ───────────────────────────────────────────
# Disse er GULL: viser hva som faktisk ble solgt og til hvilken pris.
# Drakter som solgte seg dukker gjerne opp igjen.

_EBAY_SOLD_QUERIES = [
    # Direkte Stabæk
    "stabaek shirt",
    "stabaek football shirt",
    "stabaek jersey",
    "stabæk shirt",
    # Grønn arm / teal uten Stabæk
    "Norway green sleeve football vintage",
    "Norway teal sleeve football shirt",
    "Norwegian football shirt green",
    "karcher football shirt",
    "kärcher football shirt Norway",
    # Spillere
    "allanzinho stabæk",
    "allanzinho shirt",
    "veigar stabæk",
    "nannskog shirt",
    # Merker + kontekst
    "Norway Diadora vintage football",
    "Norway 90s football shirt green",
]

_EBAY_MARKETS = [
    ("ebay.co.uk", "UK"),
    ("ebay.de",    "DE"),
    ("ebay.com",   "US"),
    ("ebay.nl",    "NL"),
    ("ebay.fr",    "FR"),
]

_ITEM_ID_RE = re.compile(r"/itm/(?:[^/]+/)?(\d+)")


def _search_ebay_sold_one(query: str, host: str) -> List[Dict]:
    """Søker eBay solgte annonser for ett søkeord på ett marked."""
    url = f"https://www.{host}/sch/i.html"
    params = {
        "_nkw":        query,
        "LH_Complete": "1",
        "LH_Sold":     "1",
        "_sacat":      "0",
        "_sop":        "10",   # nyeste først
        "_ipg":        "60",
    }
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as exc:
        logger.debug("eBay sold [%s] '%s': %s", host, query, exc)
        return []

    soup = BeautifulSoup(r.text, "lxml")
    results = []
    for item in soup.select(".s-item"):
        title_el  = item.select_one(".s-item__title")
        price_el  = item.select_one(".s-item__price")
        link_el   = item.select_one("a.s-item__link")
        img_el    = item.select_one("img.s-item__image-img")
        if not title_el or not link_el:
            continue
        title = title_el.get_text(strip=True)
        if "Shop on eBay" in title:
            continue
        href = link_el.get("href", "")
        m = _ITEM_ID_RE.search(href)
        if not m:
            continue
        results.append({
            "id":          f"ebay_sold_{m.group(1)}",
            "source":      f"{host}_sold",
            "title":       title,
            "price":       price_el.get_text(strip=True) if price_el else "",
            "url":         href.split("?")[0],
            "image_url":   img_el.get("src", "") if img_el else "",
            "description": "(tidligere solgt – historisk data)",
        })
    return results


def run_ebay_sold_scan(db: Database) -> List[Dict]:
    """Kjører alle eBay sold-søk og returnerer RELEVANTE nye funn."""
    logger.info("🔍 eBay solgte annonser – starter (%d søk × %d markeder)",
                len(_EBAY_SOLD_QUERIES), len(_EBAY_MARKETS))
    new_hits = []
    _STABÆK_WORDS = {
        "stabæk", "stabaek", "stabek", "stabak", "stabbæk",
        "allanzinho", "veigar", "nannskog", "belsvik", "bakircioglu",
        "kjønsberg", "kjoensberg", "karcher", "kärcher",
    }

    for query in _EBAY_SOLD_QUERIES:
        for host, _ in _EBAY_MARKETS:
            for ad in _search_ebay_sold_one(query, host):
                is_new = db.check_and_mark(
                    ad["id"], ad["source"], ad["title"], ad["url"]
                )
                if is_new:
                    tl = ad["title"].lower().replace("æ", "ae")
                    if any(w in tl for w in _STABÆK_WORDS):
                        new_hits.append(ad)
                        logger.info("🔍 SOLGT TREFF: %s | %s [%s]",
                                    ad["title"], ad["price"], host)
            time.sleep(1.0)

    logger.info("eBay sold ferdig – %d nye relevante funn", len(new_hits))
    return new_hits


# ── Bredt søk: grønn arm uten «stabæk» ──────────────────────────────────────
# Fanger drakter der selger ikke vet / har skrevet "Stabæk" riktig

_BROAD_SEARCHES: List[Dict] = [
    # Finn.no – norsk
    {
        "name": "finn_broad",
        "url": "https://www.finn.no/bap/forsale/search.html",
        "params": {"q": "grønn arm norsk fotball drakt vintage", "sort": "PUBLISHED_DESC"},
        "parser": "finn_html",
    },
    {
        "name": "finn_kärcher",
        "url": "https://www.finn.no/bap/forsale/search.html",
        "params": {"q": "kärcher drakt", "sort": "PUBLISHED_DESC"},
        "parser": "finn_html",
    },
    {
        "name": "finn_karcher",
        "url": "https://www.finn.no/bap/forsale/search.html",
        "params": {"q": "karcher fotballdrakt", "sort": "PUBLISHED_DESC"},
        "parser": "finn_html",
    },
    # eBay UK – green sleeve Norway
    {
        "name": "ebay_green_norway",
        "url": "https://www.ebay.co.uk/sch/i.html",
        "params": {
            "_nkw": "green sleeve Norway football vintage",
            "_sacat": "0", "_sop": "10",
        },
        "parser": "ebay_html",
    },
    {
        "name": "ebay_teal_norway",
        "url": "https://www.ebay.co.uk/sch/i.html",
        "params": {
            "_nkw": "teal sleeve Norway football shirt 90s",
            "_sacat": "0", "_sop": "10",
        },
        "parser": "ebay_html",
    },
    {
        "name": "ebay_karcher_shirt",
        "url": "https://www.ebay.co.uk/sch/i.html",
        "params": {
            "_nkw": "karcher football shirt vintage",
            "_sacat": "0", "_sop": "10",
        },
        "parser": "ebay_html",
    },
    # Marktplaats – nederlandsk
    {
        "name": "markt_green_norway",
        "url": "https://www.marktplaats.nl/q/stabaek/",
        "params": {},
        "parser": "markt_html",
    },
]

_STABÆK_BROAD = {
    "stabæk", "stabaek", "stabek", "stabak", "stabbæk",
    "allanzinho", "veigar", "nannskog", "bakircioglu",
    "karcher", "kärcher", "k-bank", "kbank",
    "norway", "norge", "norsk", "norwegian",
    "green sleeve", "grønn arm", "grønn erm", "teal sleeve",
}


def _parse_finn_html(soup: BeautifulSoup, source: str) -> List[Dict]:
    ads = []
    for art in soup.select("article[data-finn-id]"):
        finn_id = art.get("data-finn-id", "")
        title_el = art.select_one("h2")
        price_el = art.select_one(".ads__unit__content__price-tag")
        link_el  = art.select_one("a[href*='/bap/']")
        img_el   = art.select_one("img")
        if not title_el:
            continue
        ads.append({
            "id":          f"finn_{finn_id}",
            "source":      source,
            "title":       title_el.get_text(strip=True),
            "price":       price_el.get_text(strip=True) if price_el else "",
            "url":         f"https://www.finn.no{link_el['href']}" if link_el else "",
            "image_url":   img_el.get("src", "") if img_el else "",
            "description": "",
        })
    return ads


def _parse_ebay_html(soup: BeautifulSoup, source: str) -> List[Dict]:
    ads = []
    for item in soup.select(".s-item"):
        title_el = item.select_one(".s-item__title")
        price_el = item.select_one(".s-item__price")
        link_el  = item.select_one("a.s-item__link")
        img_el   = item.select_one("img.s-item__image-img")
        if not title_el or not link_el:
            continue
        title = title_el.get_text(strip=True)
        if "Shop on eBay" in title:
            continue
        href = link_el.get("href", "")
        m = _ITEM_ID_RE.search(href)
        if not m:
            continue
        ads.append({
            "id":          f"ebay_{m.group(1)}",
            "source":      source,
            "title":       title,
            "price":       price_el.get_text(strip=True) if price_el else "",
            "url":         href.split("?")[0],
            "image_url":   img_el.get("src", "") if img_el else "",
            "description": "",
        })
    return ads


def run_broad_searches(db: Database) -> List[Dict]:
    """Bredere søk – fanger drakter der tittel ikke inneholder «Stabæk»."""
    logger.info("🔍 Bredt søk (%d sources)", len(_BROAD_SEARCHES))
    new_hits = []

    for spec in _BROAD_SEARCHES:
        try:
            r = requests.get(spec["url"], params=spec["params"],
                             headers=_HEADERS, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")

            if spec["parser"] == "finn_html":
                ads = _parse_finn_html(soup, spec["name"])
            elif spec["parser"] == "ebay_html":
                ads = _parse_ebay_html(soup, spec["name"])
            else:
                ads = []

            for ad in ads:
                is_new = db.check_and_mark(
                    ad["id"], ad["source"], ad["title"], ad["url"]
                )
                if is_new:
                    tl = (ad["title"] + " " + ad.get("description", "")).lower()
                    if any(w in tl for w in _STABÆK_BROAD):
                        new_hits.append(ad)
                        logger.info("🔍 BREDT TREFF [%s]: %s", spec["name"], ad["title"])

            logger.debug("Bredt søk [%s]: %d treff", spec["name"], len(ads))
            time.sleep(2.0)

        except Exception as exc:
            logger.debug("Bredt søk [%s] feil: %s", spec["name"], exc)

    logger.info("Bredt søk ferdig – %d nye relevante funn", len(new_hits))
    return new_hits


# ── Statistikk ───────────────────────────────────────────────────────────────

def get_stats(db: Database) -> Dict:
    """Samler statistikk fra database, loggfil og bilde-cache."""
    stats = {
        "total_seen":         db.count(),
        "seen_today":         0,
        "scan_rounds_total":  0,
        "scan_rounds_today":  0,
        "deep_scans_today":   0,
        "hits_today":         0,
        "errors_today":       0,
        "images_analyzed":    0,
        "images_green":       0,
        "per_source":         [],
        "monitor_running":    False,
    }

    today = datetime.now().strftime("%Y-%m-%d")

    # ── Database ────────────────────────────────────────────────────────────
    try:
        conn = sqlite3.connect(db.path)
        row = conn.execute(
            "SELECT COUNT(*) FROM seen_ads WHERE seen_at >= datetime('now', '-24 hours')"
        ).fetchone()
        stats["seen_today"] = row[0] if row else 0

        rows = conn.execute(
            "SELECT source, COUNT(*) cnt FROM seen_ads "
            "GROUP BY source ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        stats["per_source"] = [(r[0], r[1]) for r in rows]
        conn.close()
    except Exception:
        pass

    # ── Loggfil ─────────────────────────────────────────────────────────────
    log_path = Path("monitor.log")
    if log_path.exists():
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "Sjekk ferdig" in line:
                        stats["scan_rounds_total"] += 1
                        if today in line:
                            stats["scan_rounds_today"] += 1
                    if "NYTT TREFF" in line and today in line:
                        stats["hits_today"] += 1
                    if "deep_scan" in line and "Rapport sendt" in line and today in line:
                        stats["deep_scans_today"] += 1
                    if "[ERROR" in line and today in line:
                        stats["errors_today"] += 1
        except Exception:
            pass

    # ── Bilde-cache ─────────────────────────────────────────────────────────
    try:
        conn = sqlite3.connect("image_cache.db")
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(has_green),0) FROM image_cache"
        ).fetchone()
        if row:
            stats["images_analyzed"] = row[0] or 0
            stats["images_green"]    = row[1] or 0
        conn.close()
    except Exception:
        pass

    # ── Monitor kjørende? ───────────────────────────────────────────────────
    import subprocess
    try:
        r = subprocess.run(
            ["pgrep", "-f", "monitor.py"], capture_output=True, text=True
        )
        stats["monitor_running"] = bool(r.stdout.strip())
    except Exception:
        pass

    return stats


def format_report(stats: Dict, ebay_hits: List[Dict], broad_hits: List[Dict]) -> str:
    """Formaterer full statistikkrapport for Telegram."""
    now    = datetime.now().strftime("%d.%m.%Y %H:%M")
    status = "🟢 Aktiv" if stats["monitor_running"] else "🔴 IKKE kjørende!"

    # Beregn tid siden siste sjekk
    minutes_per_round  = 3
    est_total_searches = stats["scan_rounds_total"] * 18   # ~18 kilder per runde

    lines = [
        f"📊 <b>Stabæk Monitor – statusrapport</b>",
        f"<i>{now}</i>",
        "",
        f"🔌 Status: <b>{status}</b>",
        "",
        "── 🔄 Monitorrunder ──────────────────",
        f"  I dag:   <b>{stats['scan_rounds_today']}</b> runder",
        f"  Totalt:  <b>{stats['scan_rounds_total']}</b> runder",
        f"  (Ca. hvert {minutes_per_round}. minutt automatisk)",
        f"  Est. kilde-søk totalt: ~{est_total_searches:,}",
        "",
        "── 📋 Annonser ───────────────────────",
        f"  Sett i dag:   <b>{stats['seen_today']}</b>",
        f"  Sett totalt:  <b>{stats['total_seen']}</b>",
        f"  ⭐ Nye treff i dag: <b>{stats['hits_today']}</b>",
        "",
        "── 🖼 Bildeanalyse ───────────────────",
        f"  Bilder analysert: <b>{stats['images_analyzed']}</b>",
        f"  🟢 Grønn farge funnet: <b>{stats['images_green']}</b>",
    ]

    # Topp 5 kilder
    if stats["per_source"]:
        lines += ["", "── 📡 Topp 5 kilder ──────────────────"]
        for src, cnt in stats["per_source"][:5]:
            lines.append(f"  • {src}: {cnt}")

    # Dybdesøk-resultater
    all_deep = ebay_hits + broad_hits
    if all_deep:
        lines += [
            "",
            f"── 🔍 Dybdesøk: {len(all_deep)} nye funn ──────",
        ]
        for hit in all_deep[:8]:
            title = hit["title"][:55]
            price = f" | {hit['price']}" if hit.get("price") else ""
            src   = hit.get("source", "")
            lines.append(f"  📌 <b>{title}</b>{price}")
            lines.append(f"     [{src}]")
            if hit.get("url"):
                lines.append(f'     <a href="{hit["url"]}">Se annonse</a>')
        if len(all_deep) > 8:
            lines.append(f"  … og {len(all_deep) - 8} til.")
    else:
        lines += [
            "",
            "── 🔍 Dybdesøk ────────────────────────",
            "  Ingen nye funn utover standard-søk.",
        ]

    # Advarsler
    if stats["errors_today"] > 10:
        lines += ["", f"⚠️ {stats['errors_today']} logg-feil i dag – sjekk monitor.log"]

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🟢 Passer på! Neste dybdesøk ~3t.",
    ]

    return "\n".join(lines)


# ── Hoved ────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler("monitor.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    cfg     = load_config()
    token   = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg["telegram"]["bot_token"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")   or cfg["telegram"]["chat_id"]
    tg      = Telegram(token, chat_id)
    db      = Database(cfg["database"]["path"])

    tg.send_text("🔍 <b>Dybdesøk startet…</b> (eBay solgte annonser + bredere søk)")

    # 1. eBay solgte annonser
    ebay_hits  = run_ebay_sold_scan(db)

    # 2. Bredere søk
    broad_hits = run_broad_searches(db)

    # 3. Statistikk
    stats = get_stats(db)

    # 4. Send varsler for hvert treff
    all_hits = ebay_hits + broad_hits
    for hit in all_hits:
        tg.send_ad(hit, score=2, match_reason="🔍 Dybdesøk-treff")

    # 5. Rapport
    report = format_report(stats, ebay_hits, broad_hits)
    tg.send_text(report)
    logger.info("deep_scan: Rapport sendt. %d nye treff.", len(all_hits))


if __name__ == "__main__":
    main()
