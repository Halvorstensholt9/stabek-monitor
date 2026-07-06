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

from database       import Database
from filters         import evaluate
from notifier        import Telegram
from image_analyzer  import has_green_sleeve

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
from scrapers.classickits           import ClassicKitsNoScraper
from scrapers.websearch             import WebSearchScraper
from scrapers.tise                  import TiseScraper
from scrapers.facebook_marketplace  import FacebookMarketplaceScraper
from scrapers.footballshirtcollective import FootballShirtCollectiveScraper
from scrapers.kleinanzeigen          import KleinanzeigenScraper
from scrapers.oldfootballshirts       import OldFootballShirtsScraper

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("ultra")


# ── Vid søkeordliste – brukes på ALLE kilder ─────────────────────────────────

QUERIES = [
    # ── Klubbnavn (alle kjente skrivemåter inkl. dobbelt-k og utenlandske) ──
    "stabæk", "stabaek", "stabek", "stabak", "stabbæk",
    "stabækk", "stabekk", "stabæck", "stabeck", "stabech",
    "stabaek fotball", "stabaek if", "stabæk if", "stabæk fotball",
    "stabækk fotball", "stabekk fotball", "stabeck fotball",
    "stabæk football", "stabaek football", "stabaek FC",
    "stabaek bærum", "stabaek bærum if",
    # ── Drakt-typer på 5+ språk ─────────────────────────────────────
    "stabæk drakt", "stabaek shirt", "stabaek jersey", "stabaek trikot",
    "stabæk trøye", "stabæk hjemmedrakt", "stabæk bortedrakt",
    "stabaek tröja", "stabaek trøje", "stabaek voetbalshirt",
    "stabaek camiseta", "stabaek maglia",
    "stabaek fotbal", "stabaek fußball", "stabaek soccer",
    # ── Spillere (bekreftede Stabæk-spillere) ───────────────────────
    "allanzinho", "allanzinho stabæk", "allanzinho shirt",
    "bakircioglu", "bakircioglu stabaek", "kennedy bakircioglu",
    "nannskog", "nannskog stabaek", "martin nannskog",
    "veigar", "veigar gunnarsson", "veigar páll",
    "kjønsberg", "kjoensberg", "rune kjønsberg",
    "belsvik", "pål belsvik",
    "lambech", "lambech stabaek", "lambech 10",
    "christer george",
    "stabaek brage tobiassen",  # andre spillere bekreftet
    "stabaek wilhelmsson",
    "stabaek sigurdsson",
    # ── Sponsorer (alltid kombinert med Stabæk) ─────────────────────
    "stabæk kärcher", "stabaek karcher", "stabaek kärcher",
    "stabæk k-bank", "stabaek kbank", "stabaek k bank",
    # ── Merker ──────────────────────────────────────────────────────
    "stabaek diadora", "stabaek umbro", "stabaek adidas", "stabaek kelme",
    "stabæk diadora", "stabæk umbro", "stabæk adidas",
    # ── År (vintage-perioden + spesielle) ───────────────────────────
    "stabaek 1990", "stabaek 1991", "stabaek 1992", "stabaek 1993",
    "stabaek 1994", "stabaek 1995", "stabaek 1996", "stabaek 1997",
    "stabaek 1998", "stabaek 1999",
    "stabaek 2000", "stabaek 2001", "stabaek 2002", "stabaek 2003", "stabaek 2004",
    # ── Vintage/retro/stil ──────────────────────────────────────────
    "stabaek vintage", "stabæk vintage", "stabaek retro", "stabæk retro",
    "stabaek 90s", "stabaek 1990s", "stabæk 90-tall", "stabæk gammel",
    "stabæk original",
    # ── Grønn arm / teal-spesifikke (på flere språk) ────────────────
    "stabaek green sleeve", "stabaek green arm", "stabaek teal sleeve",
    "stabæk grønne ermer", "stabæk grønn arm", "stabæk grønnerm",
    "stabaek turquoise sleeve", "stabaek teal", "stabaek long sleeve",
    "stabaek langermet", "stabæk langermet drakt",
    # ── Generelt vintage norsk fotball ──────────────────────────────
    "norway diadora football", "norway vintage diadora",
    "norway 90s football green", "norwegian football green sleeve",
    "norway football shirt teal", "norwegian vintage soccer jersey",
    "norsk fotballdrakt 90-tall", "norsk vintage drakt",
    # ── Matchworn/signert/spillerdrakt ──────────────────────────────
    "stabaek matchworn", "stabæk match worn", "stabæk signert",
    "stabaek player issue", "stabaek spillerdrakt", "stabaek kampbrukt",
    "stabaek utøverbrukt", "stabaek signed",
    # ── Auksjon / selges ────────────────────────────────────────────
    "stabaek drakt selges", "stabaek shirt for sale", "stabaek auction",
    "stabæk drakt auksjon", "stabaek samling",

    # ── STØRSTE-SØK-TILLEGG (ekstra bredde) ─────────────────────────
    # Sponsor + drakt-kombinasjoner
    "stabæk kärcher drakt", "stabaek karcher shirt", "stabaek kbank trøye",
    # Farge × type-kombinasjoner (grønn-arm-jakten)
    "stabaek hvit grønn drakt", "stabaek blå grønn", "stabaek teal hvit",
    "stabaek green white shirt", "stabaek turquoise jersey",
    "stabæk stripet drakt", "stabæk diadora grønn",
    # Drakt-detaljer
    "stabæk keeper drakt", "stabæk målvakt", "stabaek goalkeeper",
    "stabæk barn drakt", "stabæk junior", "stabaek kids shirt",
    "stabæk langermet vintage", "stabaek long sleeve 90s",
    # Nye stavemåter × type
    "stabækk drakt", "stabekk fotballdrakt", "stabæck shirt",
    "stabeck trikot", "stabbæk drakt",
    # Spillere × år/type (flere Stabæk-spillere fra gullperioden)
    "stabaek gunnarsson", "stabaek páll", "stabaek hoff",
    "stabaek bergdølmo", "stabaek finstad", "stabaek hauger",
    "stabaek wilhelmsson drakt", "stabaek sigurdsson drakt",
    "stabaek brage tobiassen",
    # Engelske marked-fraser
    "norwegian eliteserien shirt vintage", "tippeligaen shirt 1990s",
    "norway club shirt diadora 90s", "scandinavian football shirt teal",
    "rare norwegian football jersey green",
    # Auksjon/samler internasjonalt
    "stabaek matchworn jersey", "stabaek signed shirt vintage",
    "stabaek player issue 1990s", "stabaek collectors shirt",
    # Generisk Diadora norsk (Stabæk brukte Diadora i grønn-arm-perioden)
    "diadora norway 1998 shirt", "diadora norwegian club green",

    # ── Tyske varianter (Kleinanzeigen.de) ──────────────────────────
    "stabaek trikot", "stabæk trikot", "stabaek jf", "stabaek norwegen",
    "stabaek legea", "stabaek fußball", "stabaek fussball trikot",
    "norwegen trikot vintage", "norwegen fußball diadora",
    "stabaek heimtrikot", "stabaek auswärtstrikot",
    # ── Flere spiller/sponsor-kombinasjoner ─────────────────────────
    "stabaek if drakt grønn", "stabæk if grønne ermer",
    "stabaek bærum drakt", "stabaek diadora 1999 home",
    "stabaek umbro vintage", "stabaek kelme drakt",
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


def run_deep(cfg, db, tg, fc):
    """Kjør det ultra-dype søket med et DELT db/tg. Kalles fra monitor-løkka
    hver 3.–4. time (samme dedup-lager = ingen gjentakelser) og av main()
    ved manuell/standalone kjøring."""
    import os
    # (navn, scraper-funksjon, pause-mellom-søk)
    sources = [
        ("finn",        FinnScraper().search,             3.0),
        ("ebay",        EbayScraper().search,             2.5),
        ("tise",        TiseScraper().search,             4.0),   # Playwright = treg
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
        ("classickits", ClassicKitsNoScraper().search,    1.5),
        ("websearch",   WebSearchScraper().search,        3.0),
        ("facebook",    FacebookMarketplaceScraper().search, 3.0),
        ("fsc",         FootballShirtCollectiveScraper().search, 1.5),
        ("kleinanzeigen", KleinanzeigenScraper().search,    2.5),
        ("oldfootballshirts", OldFootballShirtsScraper().search, 2.0),
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

            # Bildeanalyse på Stabæk-drakter eller spiller-titler (samme
            # som monitor.py) – beriker beskrivelsen hvis grønt erme.
            _STAB = {"stabæk","stabaek","stabek","stabak","stabbæk",
                     "stabækk","stabekk","stabæck","stabeck"}
            _JERS = {"drakt","trøye","jersey","shirt","trikot"}
            _PLYR = {"allanzinho","bakircioglu","nannskog","veigar",
                     "kjønsberg","kjoensberg","belsvik","lambech","christer george"}
            _tlc = ad.get("title","").lower().replace("\xe6","ae")
            if ad.get("image_url") and (
                (any(t in _tlc for t in _STAB) and any(w in _tlc for w in _JERS))
                or any(p in _tlc for p in _PLYR)
            ):
                if has_green_sleeve(ad["image_url"]):
                    desc = ad.get("description","").strip()
                    ad["description"] = (desc + " | grønne ermer (bildeanalyse)").strip(" |")

            keep, score, reason = evaluate(ad, fc)
            if not keep:
                skipped_filt += 1
                continue

            # Obligatorisk verifisering av 🟢 GRØNNE ERMER
            if "GRØNNE ERMER" in reason and ad.get("image_url"):
                if not has_green_sleeve(ad["image_url"]):
                    reason = ("tekst sa grønn, bilde sier nei | "
                              + reason.replace("🟢 GRØNNE ERMER | ","").replace("🟢 GRØNNE ERMER","").strip(" |"))
                    score = max(1, score - 15)

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


def main():
    """Standalone/manuell kjøring: bygg eget db/tg og kjør dypsøket."""
    import os
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    db = Database(cfg["database"]["path"])
    token   = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg["telegram"]["bot_token"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")   or cfg["telegram"]["chat_id"]
    tg = Telegram(token, chat_id)
    fc = cfg["filters"]
    # Stille re-priming hvis lageret er tomt (ny cache)
    if db.was_empty:
        tg.send_ad   = lambda *a, **k: None
        tg.send_text = lambda *a, **k: None
    run_deep(cfg, db, tg, fc)


if __name__ == "__main__":
    main()
