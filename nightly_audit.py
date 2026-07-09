#!/usr/bin/env python3
"""
Nattlig selvrevisjon (kl 02:00 – kjøres av audit.yml).

Går over ALT:
  1. Kilde-helse: prøver hver eneste scraper – svarer den?
  2. System: konfig laster, filteret gir riktig svar på kjente tilfeller,
     bildeanalyse importerbar.
  3. Gjennomgang av det som er SENDT siste døgn (sent_log.jsonl) – re-validerer
     hver melding mot filteret + spam-mønster og flagger noe som ser feil ut.

Sender ÉN kort rapport til Telegram. Ingen scraping-varsler herfra.
"""

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import yaml

cfg   = yaml.safe_load(open("config.yaml", encoding="utf-8"))
token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg["telegram"]["bot_token"]
chat  = os.environ.get("TELEGRAM_CHAT_ID")   or cfg["telegram"]["chat_id"]
OSLO  = timezone(timedelta(hours=2))


def tg(msg: str):
    subprocess.run(
        ["curl", "-sS", "--max-time", "25", "-X", "POST",
         f"https://api.telegram.org/bot{token}/sendMessage",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"chat_id": chat, "text": msg, "parse_mode": "HTML"})],
        capture_output=True, text=True)


# ── 1. KILDE-HELSE ──────────────────────────────────────────────────────
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
from scrapers.marktplaats import MarktplaatsScraper
from scrapers.grailed import GrailedScraper
from scrapers.cultkits import CultKitsScraper
from scrapers.classickits import ClassicKitsNoScraper
from scrapers.websearch import WebSearchScraper
from scrapers.facebook_marketplace import FacebookMarketplaceScraper
from scrapers.footballshirtcollective import FootballShirtCollectiveScraper
from scrapers.kleinanzeigen import KleinanzeigenScraper
from scrapers.oldfootballshirts import OldFootballShirtsScraper
from scrapers.subito import SubitoScraper
from scrapers.leboncoin import LeboncoinScraper
from scrapers.olx import OLXScraper
from scrapers.poshmark import PoshmarkScraper
from scrapers.draktgata import DraktgataScraper

SOURCES = [
    ("finn", FinnScraper), ("ebay", EbayScraper), ("tise", TiseScraper),
    ("vinted", VintedScraper), ("forza", ForzaScraper), ("cfs", ClassicFCScraper),
    ("tradera", TraderaScraper), ("blocket", BlocketScraper), ("dba", DbaScraper),
    ("depop", DepopScraper), ("vfs", VintageFCScraper), ("reddit", RedditScraper),
    ("catawiki", CatawikiScraper), ("tfi", FootballIdiotsScraper),
    ("marktplaats", MarktplaatsScraper), ("grailed", GrailedScraper),
    ("cultkits", CultKitsScraper), ("classickits", ClassicKitsNoScraper),
    ("websearch", WebSearchScraper), ("facebook", FacebookMarketplaceScraper),
    ("fsc", FootballShirtCollectiveScraper), ("kleinanzeigen", KleinanzeigenScraper),
    ("oldfootballshirts", OldFootballShirtsScraper), ("subito", SubitoScraper),
    ("leboncoin", LeboncoinScraper), ("olx", OLXScraper), ("poshmark", PoshmarkScraper),
    ("draktgata", DraktgataScraper),
]


def _probe(name, S):
    try:
        S().search("stabaek")     # svarer den uten exception?
        return name, True
    except Exception:
        return name, False


health = {}
with ThreadPoolExecutor(max_workers=len(SOURCES)) as ex:
    futs = {ex.submit(_probe, n, S): n for n, S in SOURCES}
    for f in as_completed(futs):
        try:
            n, ok = f.result(timeout=120)
        except Exception:
            n, ok = futs[f], False
        health[n] = ok
down = sorted([n for n, ok in health.items() if not ok])

# ── 2. SYSTEM-SJEKK ─────────────────────────────────────────────────────
sys_notes = []
try:
    from filters import evaluate
    fc = cfg["filters"]
    checks = [
        ({"title": "Stabæk Diadora 1998 home shirt", "description": ""}, True),
        ({"title": "Macron Stabaek Away 2020 Shirt", "description": ""}, False),
        ({"title": "Stabæk drakt ønskes kjøpt", "description": ""}, False),
        ({"title": "Liverpool 2005 home shirt", "description": ""}, False),
    ]
    for ad, want in checks:
        ok, _, _ = evaluate(ad, fc)
        if ok != want:
            sys_notes.append(f"filter: «{ad['title'][:22]}»")
except Exception as exc:
    sys_notes.append(f"filter-feil: {str(exc)[:30]}")
try:
    import image_analyzer  # noqa: F401
except Exception:
    sys_notes.append("image_analyzer import-feil")
sys_ok = not sys_notes

# ── 3. GJENNOMGANG AV SENDT SISTE DØGN ──────────────────────────────────
sent = []
try:
    now = time.time()
    for ln in open("sent_log.jsonl", encoding="utf-8"):
        try:
            d = json.loads(ln)
            if now - d.get("ts", 0) < 24 * 3600:
                sent.append(d)
        except Exception:
            pass
except Exception:
    pass

suspicious = []
try:
    from filters import evaluate
    fc = cfg["filters"]
    for d in sent:
        ad = {"title": d.get("title", ""), "description": d.get("reason", "")}
        try:
            ok, _, _ = evaluate(ad, fc)
        except Exception:
            ok = True
        low = (d.get("title", "") + " " + d.get("url", "")).lower()
        spammy = any(p in low for p in
                     ("worldwide delivery", "we offer only", "for sale -"))
        if (not ok) or spammy:
            suspicious.append(d.get("title", "")[:38])
except Exception:
    pass

# ── RAPPORT ─────────────────────────────────────────────────────────────
up = len(health) - len(down)
lines = [f"🌙 <b>Nattlig selvrevisjon</b> ({datetime.now(OSLO).strftime('%d.%m kl %H:%M')})"]
lines.append(f"📡 Kilder: <b>{up}/{len(health)} svarer</b>"
             + (f"\n🔴 Nede: {', '.join(down)}" if down else " · ✅ alle OK"))
lines.append(f"⚙️ System: " + ("✅ OK" if sys_ok else "⚠️ " + "; ".join(sys_notes)))
if sent:
    lines.append(f"📨 Sendt siste døgn: <b>{len(sent)}</b>"
                 + (f"\n⚠️ {len(suspicious)} ser mistenkelige ut: "
                    + ", ".join(suspicious[:5])
                    if suspicious else " · alle ser riktige ut ✅"))
else:
    lines.append("📨 Ingen varsler sendt siste døgn.")

if down or not sys_ok or suspicious:
    lines.append("\n<i>⚠️ Noe bør ses over.</i>")
else:
    lines.append("\n<i>Alt fungerer som det skal. God natt 🌙</i>")

tg("\n".join(lines))
print(f"Nattlig sjekk sendt. down={down} sys_ok={sys_ok} sent={len(sent)} "
      f"suspicious={len(suspicious)}")
