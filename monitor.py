#!/usr/bin/env python3
"""
Stabæk Drakt Monitor
──────────────────────────────────────────────────────────────────
Overvåker 12 nettsteder parallelt for vintage Stabæk-drakter.
Alle scrapers kjøres samtidig – full sjekk tar ~45 sek.
Bruk: python monitor.py [--test]
"""

import argparse
import logging
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Dict

import schedule
import yaml

from database import Database
from filters import evaluate
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
    logger = logging.getLogger(f"source.{name}")
    new_hits = 0
    for kw in keywords:
        try:
            ads = search_fn(kw)
        except Exception as exc:
            logger.error("Uventet feil: %s", exc)
            ads = []

        for ad in ads:
            is_new = db.check_and_mark(
                ad["id"], ad["source"],
                ad.get("title", ""), ad.get("url", ""),
            )
            if not is_new:
                continue

            keep, score, reason = evaluate(ad, filter_cfg)
            if keep:
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


# ── Hoved-sjekk ───────────────────────────────────────────────────────────

def run_check(cfg: dict, db: Database, tg: Telegram) -> int:
    logger  = logging.getLogger("monitor")
    s       = cfg["search"]
    fc      = cfg["filters"]

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

    # (navn, søkefunksjon, nøkkelordliste, pause_sek)
    sources = [
        ("finn",    finn.search,   s.get("finn_keywords",    []), 4.0),
        ("ebay",    ebay.search,   s.get("ebay_keywords",    []), 2.0),
        ("tise",    tise.search,   s.get("tise_keywords",    []), 3.0),
        ("vinted",  vinted.search, s.get("vinted_keywords",  []), 3.0),
        ("forza",   forza.search,  s.get("forza_keywords",   []), 2.0),
        ("cfs",     cfs.search,    s.get("cfs_keywords",     []), 2.0),
        ("tradera", trad.search,   s.get("tradera_keywords", []), 2.0),
        ("blocket", blk.search,    s.get("blocket_keywords", []), 2.0),
        ("dba",     dba.search,    s.get("dba_keywords",     []), 2.0),
        ("depop",   dep.search,    s.get("depop_keywords",   []), 2.0),
        ("vfs",     vfs.search,    s.get("vfs_keywords",     []), 2.0),
    ]

    logger.info("══ Starter sjekk (%d kilder parallelt) ══", len(sources))
    t0 = time.monotonic()
    total_new = 0

    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="scraper") as pool:
        futures = {
            pool.submit(_run_source, name, fn, kws, db, tg, fc, pause): name
            for name, fn, kws, pause in sources
            if kws  # hopp over kilder uten nøkkelord
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
    import os
    token   = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg["telegram"]["bot_token"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")   or cfg["telegram"]["chat_id"]

    if "DIN_BOT_TOKEN_HER" in token:
        sys.exit("❌  Sett TELEGRAM_BOT_TOKEN som miljøvariabel, eller fyll inn i config.yaml")

    tg = Telegram(token, chat_id)
    db = Database(cfg["database"]["path"])

    if not tg.verify_connection():
        sys.exit("❌  Klarer ikke å koble til Telegram. Sjekk bot_token.")

    if args.test:
        logger.info("── TEST-MODUS ──")
        tg.send_text("🔍 <b>Test-kjøring startet</b>\nSjekker alle 11 nettsteder…")
        hits = run_check(cfg, db, tg)
        tg.send_text(
            f"✅ Test fullført – {hits} nye treff.\n"
            + ("Sjekk meldingene over!" if hits else "Ingen treff akkurat nå – det betyr at alt fungerer!")
        )
        return

    interval = cfg["search"].get("interval_minutes", 6)
    source_count = sum(
        1 for k in ("finn_keywords","ebay_keywords","tise_keywords","vinted_keywords",
                    "forza_keywords","cfs_keywords","tradera_keywords","blocket_keywords",
                    "dba_keywords","depop_keywords","vfs_keywords")
        if cfg["search"].get(k)
    )

    logger.info(
        "Stabæk Drakt Monitor startet – %d kilder, sjekker hvert %d. minutt.",
        source_count, interval,
    )
    tg.send_text(
        f"🟢 <b>Stabæk Drakt Monitor startet!</b>\n"
        f"📡 {source_count} nettsteder sjekkes hvert {interval}. minutt\n"
        f"Finn.no · eBay (5 markeder) · Tise · Vinted\n"
        f"Tradera · Blocket · DBA · Depop · Forza · CFS · VFS\n"
        f"Du varsles umiddelbart ved nye treff. 🏆"
    )

    run_check(cfg, db, tg)

    schedule.every(interval).minutes.do(run_check, cfg=cfg, db=db, tg=tg)
    logger.info("Trykk Ctrl+C for å stoppe.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(20)
    except KeyboardInterrupt:
        logger.info("Monitor stoppet.")
        tg.send_text("🔴 Monitor stoppet.")


if __name__ == "__main__":
    main()
