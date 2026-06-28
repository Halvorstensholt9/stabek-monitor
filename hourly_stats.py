#!/usr/bin/env python3
"""
Time-rapport kl :45 – sender statistikk til Telegram.

Kjøres av egen GitHub Actions-jobb hvert hele time (minutt 45).
Leser akkumulerte tellere fra stats.json (i sky-cachen) + antall
annonser i seen_ads.db, og sender en kompakt rapport. Ingen scraping.
"""

import json
import os
import sqlite3
import subprocess
from datetime import datetime

import yaml

cfg   = yaml.safe_load(open("config.yaml", encoding="utf-8"))
token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg["telegram"]["bot_token"]
chat  = os.environ.get("TELEGRAM_CHAT_ID")   or cfg["telegram"]["chat_id"]

# Akkumulerte tellere (seedet med lokal historikk i monitor.py)
try:
    s = json.load(open("stats.json"))
except Exception:
    s = {"all_runs": 973, "all_searches": 562333, "all_hits": 309,
         "day_runs": 0, "day_searches": 0, "day_hits": 0,
         "last_sources": 23, "last_dead": [], "last_total": 0}

try:
    ads = sqlite3.connect(cfg["database"]["path"]).execute(
        "SELECT COUNT(*) FROM seen_ads").fetchone()[0]
except Exception:
    ads = s.get("last_total", 0)

dead = s.get("last_dead", [])
health_line = ("✅ alle kilder OK" if not dead
               else f"⚠️ {len(dead)} nede: " + ", ".join(dead))

msg = (
    f"🔍 <b>Stabæk-bot – timesjekk</b>  ({datetime.now().strftime('%H:%M')})\n"
    f"📡 {s.get('last_sources', 23)} kilder · {health_line}\n\n"
    f"<b>I dag:</b> {s.get('day_runs',0)} runder · "
    f"{s.get('day_searches',0):,} søk · {s.get('day_hits',0)} treff\n"
    f"<b>All-time:</b> {s.get('all_runs',0):,} runder · "
    f"{s.get('all_searches',0):,} søk · {s.get('all_hits',0)} treff\n"
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
print(f"DEBUG stats: all_runs={s.get('all_runs')} all_searches={s.get('all_searches')} "
      f"day_runs={s.get('day_runs')} day_searches={s.get('day_searches')} "
      f"stats.json finnes={os.path.exists('stats.json')}")
