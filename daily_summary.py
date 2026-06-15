#!/usr/bin/env python3
"""
Daglig sammendrag til Telegram – kjøres av launchd kl 09:00.

Viser:
  - Aktivitet siste 24t (søk, runder, treff)
  - Eventuelle nye annonser sendt
  - Tracking-status hvis pakken har beveget seg
  - Eventuelle vedvarende feil
"""

import re
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT       = Path(__file__).parent
LOG_FILE   = ROOT / "monitor.log"
LOG_OLD    = ROOT / "monitor.log.old"
STATE_FILE = ROOT / "tracking_state.json"
CFG        = yaml.safe_load((ROOT / "config.yaml").read_text())


def post_telegram(text: str) -> None:
    import json, time
    token = CFG["telegram"]["bot_token"]
    chat  = str(CFG["telegram"]["chat_id"])
    payload = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML"})
    # Robust: 3 forsøk med backoff, fang alle feil (curl-timeout krasjet
    # tidligere hele jobben → exit=1).
    for attempt in range(3):
        try:
            r = subprocess.run(
                ["curl", "-sS", "--max-time", "25", "-X", "POST",
                 f"https://api.telegram.org/bot{token}/sendMessage",
                 "-H", "Content-Type: application/json", "-d", payload],
                capture_output=True, timeout=30, text=True,
            )
            if '"ok":true' in (r.stdout or ""):
                return
        except Exception:
            pass
        time.sleep(3)


def main():
    # Aktivitet siste 24t (kun fra aktiv monitor.log – ikke gamle filer)
    cutoff = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
    log = LOG_FILE.read_text() if LOG_FILE.exists() else ""
    recent = [l for l in log.splitlines() if l[:16] > cutoff]

    searches = sum(1 for l in recent if re.search(r"scrapers\.[a-z_0-9]+:.*treff", l))
    rounds   = sum(1 for l in recent if "Sjekk ferdig" in l)
    hits     = sum(1 for l in recent if "NYTT TREFF" in l)
    errors   = sum(1 for l in recent if "[ERROR" in l)

    # All-time totaler (begge logger)
    all_log = log + (LOG_OLD.read_text() if LOG_OLD.exists() else "")
    total_searches = len(re.findall(r"scrapers\.[a-z_0-9]+:.*treff", all_log))
    total_hits     = all_log.count("NYTT TREFF")

    # Top-3 treff siste 24t hvis noen
    top_hits = []
    for l in recent:
        m = re.search(r"NYTT TREFF \[score=(\d+)\] (.{1,80})", l)
        if m:
            top_hits.append((int(m.group(1)), m.group(2)))
    top_hits.sort(reverse=True)

    # DB-status
    db_path = CFG["database"]["path"]
    ads_seen = sqlite3.connect(db_path).execute(
        "SELECT COUNT(*) FROM seen_ads"
    ).fetchone()[0]

    lines = [
        "🌅 <b>Morgen-rapport</b>",
        f"<i>{datetime.now().strftime('%A %d. %B kl %H:%M')}</i>",
        "",
        "<b>📊 Siste døgn</b>",
        f"• {searches:,} søk · {rounds} runder · {errors} feil",
        f"• <b>{hits} nye varsler</b> sendt",
    ]
    if top_hits:
        lines.append("")
        lines.append("<b>Topp treff i går:</b>")
        for score, title in top_hits[:3]:
            lines.append(f"• [{score}] {title[:60]}")

    lines += [
        "",
        "<b>📈 All time</b>",
        f"• {total_searches:,} søk · {ads_seen:,} unike annonser",
        f"• {total_hits} varsler · 🛒 <b>2 kjøp</b>",
    ]

    # Tracking
    if STATE_FILE.exists():
        import json
        state = json.loads(STATE_FILE.read_text())
        if state:
            lines.append("")
            lines.append("<b>📦 Forsendelser</b>")
            for sid, info in state.items():
                lines.append(f"• {info['label']}")
                lines.append(f"  {info['status'][:80]}")

    if errors > 50:
        lines.append("")
        lines.append(f"⚠️ {errors} feil i går – jeg sjekker årsaken")

    post_telegram("\n".join(lines))
    print(f"Sendt sammendrag: {searches} søk, {hits} treff, {errors} feil")


if __name__ == "__main__":
    main()
