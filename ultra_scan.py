#!/usr/bin/env python3
"""
ULTRA-DYPT SØK – engangs-skann av ALLE fungerende kilder med vid søkeordliste.

Mer aggressivt enn både monitor og deep_scan:
  - Alle 17 fungerende skrapere (Tise hoppes over – WIP/Playwright)
  - ~60 søkeord (klubb, spillere, sponsorer, drakttyper, generisk vintage)
  - Resultater kjøres gjennom samme filter som monitoren
  - Treff sendes til Telegram via vanlig send_ad()
  - Avslutter med detaljert sammendrag på Telegram
"""

import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import yaml

from database import Database
from filters   import evaluate
from notifier  import Telegram

from scrapers.finn                  import FinnScraper
from scrapers.ebay                  import EbayScraper
from scrapers.vinted                import VintedScraper
from scrapers.forza                 import ForzaScraper
from scrapers.classicfootballshirts import ClassicFCScraper
from scrapers.tradera               import TraderaScraper
from scrapers.blocket               import BlocketScraper
from scrapers.dba                   import DbaScraper
from scrapers.depop                 import DepopScraper
from scrapers.vintagefootballshirts import VintageFCScraper
from scrapers.reddit                import RedditScraper
from scrapers.catawiki              import CatawikiScraper
from scrapers.thefootballidiots     import FootballIdiotsScraper
from scrapers.draktgata             import DraktgataScraper
from scrapers.marktplaats           import MarktplaatsScraper
from scrapers.grailed               import GrailedScraper
from scrapers.cultkits              import CultKitsScraper

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("ultra")


# ── Vid søkeordliste – brukes på ALLE kilder ─────────────────────────────────

QUERIES = [
    # Klubbnavn (mange skrivemåter)
    "stabæk", "stabaek", "stabek", "stabak", "stabbæk",
    "stabaek fotball", "stabaek if", "stabæk if", "stabæk fotball",
    "stabæk football", "stabaek football",
    # Drakt-typer
    "stabæk drakt", "stabaek shirt", "stabaek jersey", "stabaek trikot",
    "stabæk trøye", "stabæk hjemmedrakt", "stabæk bortedrakt",
    # Spillere (bekreftede Stabæk-spillere – fungerer som identifikator)
    "allanzinho", "allanzinho stabæk", "allanzinho shirt",
    "bakircioglu", "bakircioglu stabaek",
    "nannskog", "nannskog stabaek",
    "veigar", "veigar gunnarsson", "veigar páll",
    "kjønsberg", "kjoensberg",
    "belsvik", "pål belsvik",
    "lambech", "lambech stabaek",          # bekreftet via Grailed-kjøp
    "christer george",
    # Sponsorer (kombinert med stabæk for trygghet)
    "stabæk kärcher", "stabaek karcher", "stabaek kärcher",
    "stabæk k-bank", "stabaek kbank",
    # Merker
    "stabaek diadora", "stabaek umbro", "stabaek adidas",
    "stabæk diadora", "stabæk umbro",
    # Vintage/grønn-arm-spesifikke
    "stabaek 1998", "stabaek 1999", "stabaek 2000",
    "stabaek vintage", "stabæk retro", "stabaek 90s",
    "stabaek green sleeve", "stabaek green arm",
    "stabæk grønne ermer", "stabæk grønn arm",
    "stabaek teal", "stabaek turquoise", "stabaek long sleeve",
    # Generelt vintage norsk fotball (ingen Stabæk i navnet – filter rydder)
    "norway diadora football", "norway vintage diadora",
    "norway 90s football green", "norwegian football green sleeve",
    "norway football shirt teal",
    # Matchworn/signert
    "stabaek matchworn", "stabæk match worn", "stabæk signert",
    "stabaek player issue",
]


# ── Hovedløkke ──────────────────────────────────────────────────────────────

def _run_source(name, scraper_fn, pause):
    """Kjør alle queries mot én kilde og returner samlet liste."""
    out = []
    for i, q in enumerate(QUERIES, 1):
        try:
            res = scraper_fn(q)
            out.extend(res)
        except Exception as exc:
            logger.warning("  [%s] %r FEIL: %s", name, q, exc)
        if i < len(QUERIES):
            time.sleep(pause)
    logger.info("[%s] ferdig: %d treff totalt over %d søk", name, len(out), len(QUERIES))
    return out


def main():
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    db = Database(cfg["database"]["path"])
    tg = Telegram(cfg["telegram"]["bot_token"], cfg["telegram"]["chat_id"])
    fc = cfg["filters"]

    # (navn, scraper-funksjon, pause-mellom-søk)
    sources = [
        ("finn",        FinnScraper().search,             3.0),
        ("ebay",        EbayScraper().search,             2.5),
        ("vinted",      VintedScraper().search,           2.5),
        ("forza",       ForzaScraper().search,            1.5),
        ("cfs",         ClassicFCScraper().search,        2.0),
        ("tradera",     TraderaScraper().search,          2.0),
        ("blocket",     BlocketScraper().search,          2.0),
        ("dba",         DbaScraper().search,              2.0),
        ("depop",       DepopScraper().search,            2.0),
        ("vfs",         VintageFCScraper().search,        2.0),
        ("reddit",      RedditScraper().search,           2.0),
        ("catawiki",    CatawikiScraper().search,         2.5),
        ("tfi",         FootballIdiotsScraper().search,   2.0),
        ("draktgata",   DraktgataScraper().search,        2.0),
        ("marktplaats", MarktplaatsScraper().search,      2.0),
        ("grailed",     GrailedScraper().search,          2.0),
        ("cultkits",    CultKitsScraper().search,         2.0),
    ]

    logger.info("═══ ULTRA-DYPT SØK starter: %d kilder × %d søk = %d operasjoner ═══",
                len(sources), len(QUERIES), len(sources) * len(QUERIES))
    tg.send_text(
        f"🔬 <b>ULTRA-DYPT SØK starter</b>\n"
        f"{len(sources)} kilder × {len(QUERIES)} søk = "
        f"{len(sources) * len(QUERIES):,} operasjoner.\n"
        f"Sammendrag når ferdig (~10–20 min)."
    )

    t0 = time.monotonic()
    results_by_source = {}
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {pool.submit(_run_source, n, fn, p): n for n, fn, p in sources}
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                results_by_source[src] = fut.result()
            except Exception as exc:
                logger.error("[%s] krasj: %s", src, exc)
                results_by_source[src] = []

    elapsed = time.monotonic() - t0
    logger.info("═══ Skann ferdig på %.0fs ═══", elapsed)

    # Deduplikér + filter
    total_raw = sum(len(v) for v in results_by_source.values())
    seen_ids  = set()
    sent      = 0
    skipped_old   = 0
    skipped_filt  = 0
    hits_by_source = defaultdict(int)
    sample_hits   = []

    for src, ads in results_by_source.items():
        for ad in ads:
            ad_id = ad.get("id", "")
            if not ad_id or ad_id in seen_ids:
                continue
            seen_ids.add(ad_id)

            # Marker i DB – hopp over hvis allerede sett tidligere
            is_new = db.check_and_mark(
                ad_id, ad.get("source", src),
                ad.get("title", ""), ad.get("url", "")
            )
            if not is_new:
                skipped_old += 1
                continue

            keep, score, reason = evaluate(ad, fc)
            if not keep:
                skipped_filt += 1
                continue

            tg.send_ad(ad, score=score, match_reason=reason)
            hits_by_source[src] += 1
            sent += 1
            if len(sample_hits) < 10:
                sample_hits.append((src, ad.get("title", "")[:60], score, reason[:40]))

    # Sammendrags-rapport
    lines = [
        "🔬 <b>ULTRA-DYPT SØK ferdig</b>",
        f"⏱ Tid: <b>{elapsed/60:.1f} min</b>",
        f"📡 Rå-treff fra kilder: <b>{total_raw:,}</b>",
        f"🆕 Unike (etter dedup): <b>{len(seen_ids):,}</b>",
        f"♻️ Allerede sett før: <b>{skipped_old:,}</b>",
        f"🚫 Filtrert bort: <b>{skipped_filt:,}</b>",
        f"⭐ <b>Sendt som varsel: {sent}</b>",
        "",
        "<b>Treff per kilde:</b>",
    ]
    for src, _, _ in sources:
        n_raw    = len(results_by_source.get(src, []))
        n_hits   = hits_by_source.get(src, 0)
        marker   = "🟢" if n_hits else ("⚪" if n_raw > 0 else "🔴")
        lines.append(f"{marker} {src:<12}  {n_raw:>4} rå → {n_hits} varsler")

    if sample_hits:
        lines.append("\n<b>Eksempler på treff:</b>")
        for src, title, score, reason in sample_hits[:8]:
            lines.append(f"[{score}] {title} <i>({reason})</i>")

    tg.send_text("\n".join(lines))
    logger.info("Rapport sendt til Telegram. Sent=%d, dedup=%d, filt=%d",
                sent, skipped_old, skipped_filt)


if __name__ == "__main__":
    main()
