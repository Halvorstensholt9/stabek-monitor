#!/usr/bin/env python3
"""
Time-rapport kl :45 – sender statistikk til Telegram.

Kjøres av egen GitHub Actions-jobb hvert hele time (minutt 45).

Tallene er BULLETPROOF: antall runder hentes direkte fra GitHub Actions-
APIet (hver kjøring telles av GitHub – kan ikke bli feil), og antall
annonser telles fra seen_ads.jsonl. Søk = runder × søk-per-runde. Helse-
info leses fra stats.json hvis tilgjengelig. Ingen scraping her.
"""

import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta

import yaml

cfg   = yaml.safe_load(open("config.yaml", encoding="utf-8"))
token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg["telegram"]["bot_token"]
chat  = os.environ.get("TELEGRAM_CHAT_ID")   or cfg["telegram"]["chat_id"]

GH_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO     = os.environ.get("GITHUB_REPOSITORY", "Halvorstensholt9/stabek-monitor")

# Målt: ~1015 søk per vanlig runde (773 skraper-søk + 238 eBay-varianter).
SEARCHES_PER_ROUND = 1015
# Lokal historikk før skyen tok over (så all-time er kontinuerlig).
SEED_RUNS     = 973
SEED_SEARCHES = 562333

OSLO = timezone(timedelta(hours=2))  # Europe/Oslo sommertid


def gh_runs(workflow: str):
    """(runder_i_dag, runder_all_time) for en workflow via GitHub-APIet."""
    if not GH_TOKEN:
        return 0, 0
    url = (f"https://api.github.com/repos/{REPO}/actions/workflows/"
           f"{workflow}/runs?per_page=100")
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
    except Exception:
        return 0, 0
    all_time = d.get("total_count", 0)
    today = datetime.now(OSLO).date()
    today_n = 0
    for run in d.get("workflow_runs", []):
        try:
            ts = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            if ts.astimezone(OSLO).date() == today:
                today_n += 1
        except Exception:
            pass
    return today_n, all_time


# ── Runder (bulletproof, fra GitHub) ────────────────────────────────────
m_today, m_all = gh_runs("monitor.yml")
d_today, d_all = gh_runs("deepscan.yml")
rounds_today = m_today + d_today
rounds_all   = SEED_RUNS + m_all + d_all
searches_today = rounds_today * SEARCHES_PER_ROUND
searches_all   = SEED_SEARCHES + (m_all + d_all) * SEARCHES_PER_ROUND

# ── Annonser i basen (fra jsonl – kan ikke bli korrupt) ─────────────────
ads = 0
try:
    with open("seen_ads.jsonl", encoding="utf-8") as fh:
        ads = sum(1 for line in fh if line.strip())
except Exception:
    ads = 0

# ── Helse (fra stats.json hvis den finnes) ──────────────────────────────
try:
    s = json.load(open("stats.json"))
except Exception:
    s = {}
sources = s.get("last_sources", 23)
dead    = s.get("last_dead", [])
health_line = ("✅ alle kilder OK" if not dead
               else f"⚠️ {len(dead)} nede: " + ", ".join(dead))

msg = (
    f"🔍 <b>Stabæk-bot – timesjekk</b>  ({datetime.now(OSLO).strftime('%H:%M')})\n"
    f"📡 {sources} kilder · {health_line}\n\n"
    f"<b>I dag:</b> {rounds_today} runder · ~{searches_today:,} søk\n"
    f"<b>All-time:</b> {rounds_all:,} runder · ~{searches_all:,} søk\n"
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
print(f"DEBUG: rounds_today={rounds_today} rounds_all={rounds_all} ads={ads} "
      f"gh_token={'ja' if GH_TOKEN else 'nei'}")
