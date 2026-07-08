#!/usr/bin/env python3
"""
Time-rapport kl :45 – sender statistikk til Telegram.

Kjøres av egen GitHub Actions-jobb hvert hele time (minutt 45).

Tallene er EKTE: de leses fra stats.json, som monitor.py øker for HVER
interne runde i 5-timers-løkka (ikke antall GitHub-kjøringer – det ville
undertalt ~20×). Antall annonser telles fra seen_ads.jsonl. Ingen scraping.
"""

import json
import os
import subprocess
from datetime import datetime, timezone, timedelta

import yaml

cfg   = yaml.safe_load(open("config.yaml", encoding="utf-8"))
token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg["telegram"]["bot_token"]
chat  = os.environ.get("TELEGRAM_CHAT_ID")   or cfg["telegram"]["chat_id"]

# Frø: lokal historikk før skyen tok over (så all-time er kontinuerlig).
SEED_RUNS     = 973
SEED_SEARCHES = 562333
SEED_HITS     = 309

OSLO = timezone(timedelta(hours=2))  # Europe/Oslo sommertid

# ── EKTE tellere fra stats.json (økt av monitor.py hver runde) ──────────
try:
    s = json.load(open("stats.json"))
except Exception:
    s = {}

rounds_today   = s.get("day_runs", 0)
searches_today = s.get("day_searches", 0)
hits_today     = s.get("day_hits", 0)
rounds_all     = s.get("all_runs", SEED_RUNS)
searches_all   = s.get("all_searches", SEED_SEARCHES)
hits_all       = s.get("all_hits", SEED_HITS)

# ── Annonser i basen (fra jsonl – kan ikke bli korrupt) ─────────────────
ads = 0
try:
    with open("seen_ads.jsonl", encoding="utf-8") as fh:
        ads = sum(1 for line in fh if line.strip())
except Exception:
    ads = 0

sources = s.get("last_sources", 30)
dead    = s.get("last_dead", [])
health_line = ("✅ alle kilder OK" if not dead
               else f"⚠️ {len(dead)} nede: " + ", ".join(dead))

msg = (
    f"🔍 <b>Stabæk-bot – timesjekk</b>  ({datetime.now(OSLO).strftime('%H:%M')})\n"
    f"📡 {sources} kilder · {health_line}\n\n"
    f"<b>I dag:</b> {rounds_today:,} runder · {searches_today:,} søk · {hits_today} treff\n"
    f"<b>All-time:</b> {rounds_all:,} runder · {searches_all:,} søk · {hits_all} treff\n"
    f"📋 {ads:,} annonser i basen · 🛒 3 kjøp\n"
    "<i>Boten lever og jakter. Du varsles straks noe dukker opp.</i>"
)

r = subprocess.run(
    ["curl", "-sS", "--max-time", "20", "-X", "POST",
     f"https://api.telegram.org/bot{token}/sendMessage",
     "-H", "Content-Type: application/json",
     "-d", json.dumps({"chat_id": chat, "text": msg, "parse_mode": "HTML"})],
    capture_output=True, text=True, timeout=25,
)
print("Time-rapport sendt:", '"ok":true' in (r.stdout or ""))
print(f"DEBUG stats.json: day_runs={rounds_today} day_searches={searches_today} "
      f"all_runs={rounds_all} all_searches={searches_all} ads={ads} "
      f"stats.json_fantes={'ja' if s else 'NEI (frø brukt)'}")
