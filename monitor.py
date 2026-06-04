#!/usr/bin/env python3
"""
Stabæk Drakt Monitor
──────────────────────────────────────────────────────────────────
Overvåker 14 nettsteder parallelt for vintage Stabæk-drakter.
Alle scrapers kjøres samtidig – full sjekk tar ~45–90 sek.
Bruk: python monitor.py [--test]
"""

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Dict

import schedule
import yaml

from database import Database
from filters import evaluate
from image_analyzer import has_green_sleeve
from notifier import Telegram
from scrapers.finn import FinnScraper
from scrapers.ebay import EbayScraper
from scrapers.tise import TiseScraper
from scrapers.vinted import VintedScraper
from scrapers.forza import ForzaScraper
from scrapers.classicfootballshirts import ClassicFCScraper
from scrapers.tradera import TraderaScraper
from scrapers.blocket import BlocketScraper
from scrapers.dba import DbaScraper
from scrapers.depop import DepopScraper
from scrapers.vintagefootballshirts import VintageFCScraper
from scrapers.reddit import RedditScraper
from scrapers.catawiki import CatawikiScraper
from scrapers.thefootballidiots import FootballIdiotsScraper
from scrapers.draktgata import DraktgataScraper
from scrapers.classickits import ClassicKitsNoScraper
from scrapers._532 import S532Scraper
from scrapers.websearch import WebSearchScraper
from scrapers.marktplaats import MarktplaatsScraper
from scrapers.grailed import GrailedScraper
from scrapers.cultkits import CultKitsScraper
# from scrapers.facebook import FacebookScraper  # Aktiver når du er klar


# ── Setup ────────────────────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        sys.exit(f"Finner ikke konfigurasjonsfil: {path}")
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(cfg: dict) -> None:
    log_file = cfg.get("logging", {}).get("file", "monitor.log")
    level    = getattr(logging, cfg.get("logging", {}).get("level", "INFO").upper(), logging.INFO)
    fmt      = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
    logging.basicConfig(
        level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ── Per-source worker (kjøres i tråd) ────────────────────────────────────

def _run_source(
    name: str,
    search_fn: Callable[[str], List[Dict]],
    keywords: List[str],
    db: Database,
    tg: Telegram,
    filter_cfg: dict,
    pause: float = 2.0,
) -> int:
    """Søk alle nøkkelord for én kilde og varsle om nye treff. Trådsikker."""
    logger    = logging.getLogger(f"source.{name}")
    new_hits  = 0
    seen_urls = set()   # unngå duplikater innen samme kilde-sjekk

    for kw in keywords:
        try:
            ads = search_fn(kw)
        except Exception as exc:
            logger.error("Uventet feil: %s", exc)
            ads = []

        for ad in ads:
            # Hopp over hvis vi allerede har sendt denne URL-en i denne runden
            url = ad.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)

            is_new = db.check_and_mark(
                ad["id"], ad["source"],
                ad.get("title", ""), url,
            )
            if not is_new:
                continue

            # ── Bildeanalyse: kjør på ALLE Stabæk-drakt-annonser med bilde,
            #    ikke bare ved kort beskrivelse. Fanger grønne ermer som
            #    teksten ikke nevner. Bildet er sannhetskilde.
            #
            # Også triggert ved bekreftet Stabæk-spillernavn i tittel,
            # selv om «Stabæk» ikke står der (Lambech, Allanzinho osv.).
            _STABÆK_TITLE = {"stabæk", "stabaek", "stabek", "stabak", "stabbæk",
                             "stabækk", "stabekk", "stabæck", "stabeck"}
            _JERSEY_WORD  = {"drakt", "trøye", "jersey", "shirt", "trikot"}
            _PLAYER_TITLE = {"allanzinho", "bakircioglu", "nannskog", "veigar",
                             "kjønsberg", "kjoensberg", "belsvik", "lambech",
                             "christer george"}
            _title_lc = ad.get("title", "").lower().replace("\xe6", "ae")
            _is_stabæk_title = any(t in _title_lc for t in _STABÆK_TITLE)
            _has_jersey_word = any(w in _title_lc for w in _JERSEY_WORD)
            _has_player_in_title = any(p in _title_lc for p in _PLAYER_TITLE)
            _desc = ad.get("description", "").strip()
            # Kjør bildeanalyse på alt som ser ut som en Stabæk-drakt-annonse
            # (Stabæk-tittel + drakt-ord  ELLER  bekreftet spillernavn)
            if (ad.get("image_url")
                    and ((_is_stabæk_title and _has_jersey_word) or _has_player_in_title)):
                if has_green_sleeve(ad["image_url"]):
                    if not _desc:
                        ad["description"] = "grønne ermer (funnet via bildeanalyse)"
                    else:
                        ad["description"] = _desc + " | grønne ermer (bildeanalyse)"
                    logger.info("🟢 BILDE-TREFF grønne ermer: %s", ad.get("title"))

            keep, score, reason = evaluate(ad, filter_cfg)
            if keep:
                # ── OBLIGATORISK bilde-verifisering ved 🟢 GRØNNE ERMER ──
                # Filteret kan utløse alarmen via tekst alene (selger skrev
                # «grønne ermer»), men bildet er sannhetskilden. Hvis bilde
                # finnes og det IKKE bekrefter grønt, nedgraderes alarmen.
                if "GRØNNE ERMER" in reason and ad.get("image_url"):
                    if not has_green_sleeve(ad["image_url"]):
                        logger.info("📷 Bilde benektet grønne ermer – nedgrader: %s",
                                    ad.get("title"))
                        # Fjern alarm-prefiks fra reason og senk score
                        reason = ("tekst sa grønn, bilde sier nei | "
                                  + reason.replace("🟢 GRØNNE ERMER | ", "")
                                          .replace("🟢 GRØNNE ERMER", "").strip(" |"))
                        score = max(1, score - 15)
                symbol = "⭐" if score >= 2 else "►"
                logger.info(
                    "%s NYTT TREFF [score=%d] %s | %s",
                    symbol, score, ad.get("title"), reason,
                )
                tg.send_ad(ad, score=score, match_reason=reason)
                new_hits += 1

        if len(keywords) > 1:
            time.sleep(pause)

    return new_hits


# ── Draktgata hurtigsjekk (hvert 30. sek) ───────────────────────────────

_draktgata_scraper = DraktgataScraper()

def run_draktgata_fastcheck(cfg: dict, db: Database, tg: Telegram) -> None:
    """
    Henter HELE Draktgata-lageret hvert 30. sek.
    Varsler KUN om Stabæk-drakter som dukker opp – med en gang.
    """
    logger       = logging.getLogger("draktgata.fast")
    stabæk_terms = {"stabæk", "stabaek"}
    try:
        alle = _draktgata_scraper.get_all_products()
    except Exception as exc:
        logger.error("Feil ved lagersjekk: %s", exc)
        return

    for ad in alle:
        title_lower = ad.get("title", "").lower().replace("æ", "a")
        er_stabæk   = any(t in title_lower for t in stabæk_terms)
        if not er_stabæk:
            continue

        is_new = db.check_and_mark(
            ad["id"], ad["source"],
            ad.get("title", ""), ad.get("url", ""),
        )
        if not is_new:
            continue

        logger.info("⭐ STABÆK PÅ DRAKTGATA: %s | %s", ad["title"], ad["price"])
        tg.send_ad(ad, score=3, match_reason="🚨 STABÆK på Draktgata.no!")


# ── Hoved-sjekk ───────────────────────────────────────────────────────────

def run_check(cfg: dict, db: Database, tg: Telegram) -> int:
    logger = logging.getLogger("monitor")
    s      = cfg["search"]
    fc     = cfg["filters"]

    finn   = FinnScraper()
    ebay   = EbayScraper()
    tise   = TiseScraper()
    vinted = VintedScraper()
    forza  = ForzaScraper()
    cfs    = ClassicFCScraper()
    trad   = TraderaScraper()
    blk    = BlocketScraper()
    dba    = DbaScraper()
    dep    = DepopScraper()
    vfs    = VintageFCScraper()
    reddit = RedditScraper()
    cata      = CatawikiScraper()
    tfi       = FootballIdiotsScraper()
    draktgata   = DraktgataScraper()
    marktplaats = MarktplaatsScraper()
    grailed     = GrailedScraper()
    cultkits    = CultKitsScraper()
    classickits = ClassicKitsNoScraper()
    s532        = S532Scraper()
    websearch   = WebSearchScraper()

    # (navn, søkefunksjon, nøkkelordliste, pause_sek_mellom_søk)
    sources = [
        ("finn",        finn.search,         s.get("finn_keywords",        []), 4.0),
        ("ebay",        ebay.search,         s.get("ebay_keywords",        []), 2.0),
        ("tise",        tise.search,         s.get("tise_keywords",        []), 3.0),
        ("vinted",      vinted.search,       s.get("vinted_keywords",      []), 3.0),
        ("forza",       forza.search,        s.get("forza_keywords",       []), 2.0),
        ("cfs",         cfs.search,          s.get("cfs_keywords",         []), 2.0),
        ("tradera",     trad.search,         s.get("tradera_keywords",     []), 2.0),
        ("blocket",     blk.search,          s.get("blocket_keywords",     []), 2.0),
        ("dba",         dba.search,          s.get("dba_keywords",         []), 2.0),
        ("depop",       dep.search,          s.get("depop_keywords",       []), 2.0),
        ("vfs",         vfs.search,          s.get("vfs_keywords",         []), 2.0),
        ("reddit",      reddit.search,       s.get("reddit_keywords",      []), 2.0),
        ("catawiki",    cata.search,         s.get("catawiki_keywords",    []), 3.0),
        ("tfi",         tfi.search,          s.get("tfi_keywords",         []), 2.0),
        ("draktgata",   draktgata.search,    s.get("draktgata_keywords",   []), 2.0),
        ("marktplaats", marktplaats.search,  s.get("marktplaats_keywords", []), 2.0),
        ("grailed",     grailed.search,      s.get("grailed_keywords",     []), 2.0),
        ("cultkits",    cultkits.search,     s.get("cultkits_keywords",    []), 2.0),
        ("classickits", classickits.search,  s.get("classickits_keywords", []), 1.5),
        ("532",         s532.search,         s.get("s532_keywords",        []), 1.5),
        ("websearch",   websearch.search,    s.get("websearch_keywords",   []), 3.0),
    ]

    logger.info("══ Starter sjekk (%d kilder parallelt) ══", len(sources))
    t0        = time.monotonic()
    total_new = 0

    with ThreadPoolExecutor(max_workers=len(sources), thread_name_prefix="scraper") as pool:
        futures = {
            pool.submit(_run_source, name, fn, kws, db, tg, fc, pause): name
            for name, fn, kws, pause in sources
            if kws
        }
        for future in as_completed(futures):
            src = futures[future]
            try:
                total_new += future.result()
            except Exception as exc:
                logger.error("Kilde %s krasjet: %s", src, exc)

    elapsed = time.monotonic() - t0
    total   = db.count()
    if total_new:
        logger.info(
            "Sjekk ferdig på %.0fs – %d nye relevante treff! (totalt sett: %d)",
            elapsed, total_new, total,
        )
    else:
        logger.info(
            "Sjekk ferdig på %.0fs – ingen nye treff. (totalt sett: %d)",
            elapsed, total,
        )
    return total_new


# ── Entrypoint ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Stabæk Drakt Monitor")
    parser.add_argument("--test",   action="store_true",
                        help="Kjør én sjekk og avslutt")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg)
    logger = logging.getLogger("monitor")

    # Miljøvariabler overstyrer config.yaml (brukes i sky-deploy)
    token   = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg["telegram"]["bot_token"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")   or cfg["telegram"]["chat_id"]

    if "DIN_BOT_TOKEN_HER" in token:
        sys.exit("❌  Sett TELEGRAM_BOT_TOKEN som miljøvariabel, eller fyll inn i config.yaml")

    tg = Telegram(token, chat_id)
    db = Database(cfg["database"]["path"])

    if not tg.verify_connection():
        sys.exit("❌  Klarer ikke å koble til Telegram. Sjekk bot_token.")

    # Tell opp antall aktive kilder
    source_keys = [
        "finn_keywords", "ebay_keywords", "tise_keywords", "vinted_keywords",
        "forza_keywords", "cfs_keywords", "tradera_keywords", "blocket_keywords",
        "dba_keywords", "depop_keywords", "vfs_keywords",
        "reddit_keywords", "catawiki_keywords", "tfi_keywords",
    ]
    source_count = sum(1 for k in source_keys if cfg["search"].get(k))
    kw_count     = sum(len(cfg["search"].get(k, [])) for k in source_keys)

    if args.test:
        logger.info("── TEST-MODUS ──")
        tg.send_text(
            f"🔍 <b>Test-kjøring startet</b>\n"
            f"Sjekker {source_count} nettsteder med {kw_count} søkeord…"
        )
        hits = run_check(cfg, db, tg)
        tg.send_text(
            f"✅ Test fullført – {hits} nye treff.\n"
            + ("Sjekk meldingene over!" if hits else "Ingen treff akkurat nå – alt fungerer!")
        )
        return

    interval = cfg["search"].get("interval_minutes", 3)
    logger.info(
        "Stabæk Drakt Monitor startet – %d kilder / %d søkeord, sjekker hvert %d. minutt.",
        source_count, kw_count, interval,
    )
    tg.send_text(
        f"🟢 <b>Stabæk Drakt Monitor startet!</b>\n"
        f"📡 <b>{source_count} nettsteder</b> · <b>{kw_count} søkeord</b>\n"
        f"🇳🇴 Finn · Tise · Forza\n"
        f"🌍 eBay (5 markeder) · Vinted · Depop · Reddit\n"
        f"🇬🇧 CFS · VFS · The Football Idiots · Catawiki\n"
        f"🇸🇪 Tradera · Blocket · 🇩🇰 DBA\n"
        f"⏱ Sjekker hvert {interval}. minutt. Du varsles umiddelbart! 🏆"
    )

    run_check(cfg, db, tg)

    schedule.every(interval).minutes.do(run_check, cfg=cfg, db=db, tg=tg)
    # Draktgata-fastcheck (hvert 30. sek) fjernet 2026-06-04 etter at
    # bruker kjøpte ønsket Stabæk 1997 home template. Vanlig 3-min runde
    # dekker Draktgata fremover.
    # schedule.every(30).seconds.do(run_draktgata_fastcheck, cfg=cfg, db=db, tg=tg)
    logger.info("Trykk Ctrl+C for å stoppe.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Monitor stoppet.")
        tg.send_text("🔴 Monitor stoppet.")


if __name__ == "__main__":
    main()
