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
import subprocess
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
from scrapers.facebook_marketplace import FacebookMarketplaceScraper
from scrapers.footballshirtcollective import FootballShirtCollectiveScraper
from scrapers.kleinanzeigen import KleinanzeigenScraper
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


# ── Auto-update ──────────────────────────────────────────────────────────

def check_for_updates(tg=None) -> None:
    """Sjekker om det er nye commits på GitHub. Restarter boten hvis ja."""
    logger = logging.getLogger("autoupdate")
    try:
        subprocess.run(["git", "fetch", "--quiet"], timeout=15, check=True,
                       capture_output=True)
        local  = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                         text=True).strip()
        remote = subprocess.check_output(["git", "rev-parse", "@{u}"],
                                         text=True).strip()
    except Exception as exc:
        logger.debug("Auto-update sjekk feilet: %s", exc)
        return

    if local == remote:
        return

    logger.info("Ny versjon funnet – puller og restarter…")
    try:
        subprocess.run(["git", "pull", "--quiet"], timeout=30, check=True,
                       capture_output=True)
    except Exception as exc:
        logger.error("git pull feilet: %s", exc)
        return

    if tg:
        tg.send_text("🔄 <b>Boten oppdaterer seg selv</b> – tilbake om noen sekunder…")

    os.execv(sys.executable, [sys.executable] + sys.argv)


# ── Flom-vakt ─────────────────────────────────────────────────────────────
# Maks varsler per runde. Overstiges dette, stopper boten og sender ÉN
# advarsel i stedet for å flomme. Nullstilles i starten av run_check().
import threading as _threading
_ALERT_CAP   = 14
_ALERT_LOCK  = _threading.Lock()
_alert_count = 0
_suppressed  = 0


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
    """Søk alle nøkkelord for én kilde og varsle om nye treff. Trådsikker.

    Returnerer (new_hits, helse-dict) der helse-dict har:
      errors    – antall søkeord som kastet exception
      total_ads – totalt antall rå-treff fra kilden
      kw_count  – antall søkeord
    Brukes for å oppdage døde kilder (errors == kw_count).
    """
    logger    = logging.getLogger(f"source.{name}")
    new_hits  = 0
    seen_urls = set()   # unngå duplikater innen samme kilde-sjekk
    _errors   = 0
    _total    = 0

    for kw in keywords:
        try:
            ads = search_fn(kw)
            _total += len(ads)
        except Exception as exc:
            logger.error("Uventet feil: %s", exc)
            ads = []
            _errors += 1

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
            _has_player_in_title = any(p in _title_lc for p in _PLAYER_TITLE)
            _desc = ad.get("description", "").strip()
            # Kjør bildeanalyse på ENHVER Stabæk-titlet vare (eller spillernavn).
            # Tidligere krevde vi også et drakt-ord (drakt/shirt/jersey...) –
            # men «Vintage Stabaek FC football» har ingen av dem, så grønn-arm
            # ble aldri oppdaget og brukeren gikk glipp av drakta. Stabæk-varer
            # er sjeldne nok til at vi trygt kan bildeanalysere alle.
            if (ad.get("image_url")
                    and (_is_stabæk_title or _has_player_in_title)):
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
                # ── FLOM-VAKT ────────────────────────────────────────────
                # Stopp utsending hvis én runde overstiger taket (14). Da er
                # noe galt (filter-glipp) – heller varsle ÉN gang enn å flomme.
                with _ALERT_LOCK:
                    global _alert_count, _suppressed
                    if _alert_count >= _ALERT_CAP:
                        _suppressed += 1
                        continue
                    _alert_count += 1
                tg.send_ad(ad, score=score, match_reason=reason)
                new_hits += 1

        if len(keywords) > 1:
            time.sleep(pause)

    return new_hits, {"errors": _errors, "total_ads": _total, "kw_count": len(keywords)}


# ── Draktgata hurtigsjekk (hvert 30. sek) ───────────────────────────────

_draktgata_scraper = DraktgataScraper()

def run_draktgata_fastcheck(cfg: dict, db: Database, tg: Telegram) -> None:
    """
    Henter HELE Draktgata-lageret hvert 30. sek.
    Varsler KUN om Stabæk-drakter som dukker opp – med en gang.
    """
    logger       = logging.getLogger("draktgata.fast")
    stabæk_terms = {"stabak", "stabaek"}  # etter .replace("æ", "a")
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
        tg.send_draktgata_alarm(ad)


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
    facebook    = FacebookMarketplaceScraper()
    fsc         = FootballShirtCollectiveScraper()
    kleinanz    = KleinanzeigenScraper()

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
        # NB: Draktgata håndteres KUN av run_draktgata_fastcheck (hvert 20. sek,
        # filter-bypass = varsler på ENHVER ny Stabæk-drakt uansett årstall).
        # Den må IKKE være her – ellers markerer den vanlige (filtrerende)
        # runden draktene som «sett», og fastchecken slår aldri alarm.
        # ("draktgata",   draktgata.search,    s.get("draktgata_keywords",   []), 2.0),
        ("marktplaats", marktplaats.search,  s.get("marktplaats_keywords", []), 2.0),
        ("grailed",     grailed.search,      s.get("grailed_keywords",     []), 2.0),
        ("cultkits",    cultkits.search,     s.get("cultkits_keywords",    []), 2.0),
        ("classickits", classickits.search,  s.get("classickits_keywords", []), 1.5),
        # 532.no deaktivert 2026-06-04: products.json returnerer 401 (de
        # har stengt offentlig API). HTML er JS-rendret = krever Playwright.
        # Reaktiveres hvis de gjenåpner eller hvis vi senere vil bruke Playwright.
        # ("532",         s532.search,         s.get("s532_keywords",        []), 1.5),
        ("websearch",   websearch.search,    s.get("websearch_keywords",   []), 3.0),
        ("facebook",    facebook.search,     s.get("facebook_keywords",    []), 3.0),
        ("fsc",         fsc.search,          s.get("fsc_collective_keywords", []), 1.5),
        ("kleinanzeigen", kleinanz.search,   s.get("kleinanzeigen_keywords", []), 2.5),
    ]

    logger.info("══ Starter sjekk (%d kilder parallelt) ══", len(sources))
    t0        = time.monotonic()
    total_new = 0

    # Nullstill flom-vakt for denne runden
    global _alert_count, _suppressed
    _alert_count = 0
    _suppressed  = 0

    health = {}   # kilde -> helse-dict
    with ThreadPoolExecutor(max_workers=len(sources), thread_name_prefix="scraper") as pool:
        futures = {
            pool.submit(_run_source, name, fn, kws, db, tg, fc, pause): name
            for name, fn, kws, pause in sources
            if kws
        }
        for future in as_completed(futures):
            src = futures[future]
            try:
                hits, h = future.result()
                total_new += hits
                health[src] = h
            except Exception as exc:
                logger.error("Kilde %s krasjet: %s", src, exc)
                health[src] = {"errors": 1, "total_ads": 0, "kw_count": 1, "crashed": True}

    # ── Helsesjekk: varsle om DØDE kilder ───────────────────────────────
    # En kilde regnes som «nede» hvis ALLE søkeordene kastet exception,
    # eller hele kilden krasjet. (0 treff er normalt – kun feil teller.)
    dead = set()
    for src, h in health.items():
        if h.get("crashed") or (h["kw_count"] > 0 and h["errors"] >= h["kw_count"]):
            dead.add(src)

    # Debounce via state-fil (ligger i actions/cache): varsle KUN ved endring.
    import json as _json
    _hs_path = "health_state.json"
    try:
        prev_dead = set(_json.load(open(_hs_path)))
    except Exception:
        prev_dead = set()

    newly_dead   = dead - prev_dead          # gått ned siden sist
    recovered    = prev_dead - dead          # kommet tilbake siden sist

    if newly_dead:
        logger.error("🔴 NYE DØDE KILDER: %s", ", ".join(newly_dead))
        try:
            tg.send_text(
                "⚠️ <b>KILDE(R) NEDE</b>\n"
                + "\n".join(f"🔴 {d}" for d in sorted(newly_dead))
                + "\n\n<i>Svarte med feil på alle søk – sjekk om de har "
                  "endret seg. Resten kjører normalt.</i>"
            )
        except Exception:
            pass
    if recovered:
        logger.info("🟢 GJENOPPRETTEDE KILDER: %s", ", ".join(recovered))
        try:
            tg.send_text("✅ <b>Kilde(r) oppe igjen:</b> "
                         + ", ".join(sorted(recovered)))
        except Exception:
            pass

    try:
        _json.dump(sorted(dead), open(_hs_path, "w"))
    except Exception:
        pass

    # ── Flom-vakt utløst? ────────────────────────────────────────────────
    if _suppressed > 0:
        logger.error("🚨 FLOM-VAKT: %d sendt, %d undertrykt (tak=%d)",
                     _alert_count, _suppressed, _ALERT_CAP)
        try:
            tg.send_text(
                f"🚨 <b>FLOM-VAKT UTLØST</b>\n"
                f"Boten ville sendt <b>{_alert_count + _suppressed}</b> varsler i "
                f"én runde – stoppet etter {_ALERT_CAP}.\n"
                f"Noe er sannsynligvis galt (filter-glipp / kilde-endring).\n"
                f"<i>{_suppressed} varsler holdt tilbake. Sjekk før resten slippes.</i>"
            )
        except Exception:
            pass

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
    parser.add_argument("--test",       action="store_true",
                        help="Kjør én sjekk og avslutt")
    parser.add_argument("--test-alarm", action="store_true",
                        help="Send en falsk Draktgata-alarm for å teste varslingen")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true",
                        help="Kjør én full runde + Draktgata-sjekk og avslutt "
                             "(brukes av GitHub Actions / cron i skyen)")
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

    # ── Stille re-priming etter DB-gjenoppbygging (korrupsjon) ──────────
    # Hvis databasen nettopp ble bygd på nytt, ville en normal runde
    # re-varslet HELE lageret. Vi kjører i stedet én STILLE runde som
    # bare markerer alt som sett, og sender én diskret heads-up.
    from database import DB_RESET_MARKER
    if os.path.exists(DB_RESET_MARKER):
        logger.info("DB ble gjenoppbygd – kjører STILLE re-priming (ingen varsler).")
        try:
            tg.send_text("🔧 <i>Databasen ble nullstilt (korrupt cache) – "
                         "primer stille én runde, så er alt normalt igjen. "
                         "Ingen varsler denne runden.</i>")
        except Exception:
            pass
        # Nøytraliser alle utsendinger denne kjøringen
        tg.send_ad            = lambda *a, **k: None
        tg.send_text          = lambda *a, **k: None
        tg.send_draktgata_alarm = lambda *a, **k: None
        try:
            os.remove(DB_RESET_MARKER)
        except OSError:
            pass

    # Tell opp antall aktive kilder
    source_keys = [
        "finn_keywords", "ebay_keywords", "tise_keywords", "vinted_keywords",
        "forza_keywords", "cfs_keywords", "tradera_keywords", "blocket_keywords",
        "dba_keywords", "depop_keywords", "vfs_keywords",
        "reddit_keywords", "catawiki_keywords", "tfi_keywords",
        "draktgata_keywords", "marktplaats_keywords", "grailed_keywords", "cultkits_keywords",
    ]
    source_count = sum(1 for k in source_keys if cfg["search"].get(k))
    kw_count     = sum(len(cfg["search"].get(k, [])) for k in source_keys)

    if args.test_alarm:
        logger.info("── TEST-ALARM ──")
        mock_ad = {
            "id":          "draktgata_test-stabak-1997",
            "source":      "draktgata.no",
            "title":       "Stabæk 1997 Diadora – grønne ermer (TESTMELDING)",
            "price":       "1 200 kr",
            "url":         "https://www.draktgata.no",
            "image_url":   "https://www.draktgata.no/cdn/shop/files/draktgata-logo.png",
            "description": "Dette er en test av Draktgata-alarmen.",
        }
        tg.send_draktgata_alarm(mock_ad)
        logger.info("Test-alarm sendt!")
        return

    if args.once:
        # Skydrift (GitHub Actions): én runde, ingen oppstartsmelding,
        # ingen evig løkke. Cron kjører dette på nytt hvert intervall.
        logger.info("── ÉN RUNDE (--once, sky) ──")
        hits = run_check(cfg, db, tg)
        try:
            run_draktgata_fastcheck(cfg, db, tg)
        except Exception as exc:
            logger.error("Draktgata-sjekk feilet: %s", exc)
        logger.info("Runde ferdig (--once): %d nye treff.", hits)
        return

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
    # Draktgata-fastcheck RE-AKTIVERT (ekstra vakt – nye drakter ventes).
    # Sjekker hele Draktgata-lageret hvert 20. sek, sender link umiddelbart
    # når en Stabæk-drakt dukker opp.
    schedule.every(20).seconds.do(run_draktgata_fastcheck, cfg=cfg, db=db, tg=tg)

    # Auto-update fra main: sjekk for nye commits hvert 5. min og restart.
    schedule.every(5).minutes.do(check_for_updates, tg=tg)
    logger.info("Trykk Ctrl+C for å stoppe.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(2)
    except KeyboardInterrupt:
        logger.info("Monitor stoppet.")
        tg.send_text("🔴 Monitor stoppet.")


if __name__ == "__main__":
    main()
