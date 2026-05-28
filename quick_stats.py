#!/usr/bin/env python3
"""
Rask statistikkrapport – sendes til Telegram hvert 60. minutt.
Ingen scraping, bare lesing av database + logg.
"""

import os
import re
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

import yaml

from database import Database
from notifier import Telegram


def main():
    cfg     = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    token   = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg["telegram"]["bot_token"]
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")   or cfg["telegram"]["chat_id"]
    tg      = Telegram(token, chat_id)
    db      = Database(cfg["database"]["path"])

    today = datetime.now().strftime("%Y-%m-%d")
    now   = datetime.now().strftime("%d.%m.%Y %H:%M")

    # ── Database ─────────────────────────────────────────────────────────────
    total = db.count()
    conn  = sqlite3.connect(db.path)
    seen_today = conn.execute(
        "SELECT COUNT(*) FROM seen_ads WHERE seen_at >= datetime('now', '-24 hours')"
    ).fetchone()[0]
    # Per-kilde breakdown (siste 24t)
    source_rows = conn.execute(
        "SELECT source, COUNT(*) cnt FROM seen_ads "
        "WHERE seen_at >= datetime('now', '-24 hours') "
        "GROUP BY source ORDER BY cnt DESC LIMIT 6"
    ).fetchall()
    conn.close()

    # ── Loggfil ──────────────────────────────────────────────────────────────
    rounds_today = hits_today = errors_today = 0
    log_path = Path("monitor.log")
    if log_path.exists():
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "Sjekk ferdig" in line and today in line:
                    rounds_today += 1
                if "NYTT TREFF" in line and today in line:
                    hits_today += 1
                if "[ERROR" in line and today in line:
                    errors_today += 1

    # ── Bilde-cache ───────────────────────────────────────────────────────────
    images_analyzed = images_green = 0
    try:
        conn2 = sqlite3.connect("image_cache.db")
        row = conn2.execute(
            "SELECT COUNT(*), COALESCE(SUM(has_green),0) FROM image_cache"
        ).fetchone()
        if row:
            images_analyzed, images_green = row[0] or 0, row[1] or 0
        conn2.close()
    except Exception:
        pass

    # ── Monitor kjørende? ─────────────────────────────────────────────────────
    try:
        proc = subprocess.run(["pgrep", "-f", "monitor.py"], capture_output=True, text=True)
        running = bool(proc.stdout.strip())
    except Exception:
        running = False

    status = "🟢 Kjørende" if running else "🔴 STOPPET!"

    # Estimert neste dybdesøk (enkelt – ikke spor vi det eksakt)
    est_total = rounds_today * 18   # 18 kilder per runde

    lines = [
        f"⏱ <b>Timestatistikk – {now}</b>",
        "",
        f"🔌 Monitor: <b>{status}</b>",
        "",
        f"🔄 Runder i dag: <b>{rounds_today}</b>  (~hvert 3. min)",
        f"📡 Kilde-søk i dag: <b>~{est_total:,}</b>",
        f"📋 Annonser sett i dag: <b>{seen_today}</b>",
        f"📋 Totalt sett: <b>{total:,}</b>",
        f"⭐ Nye relevante treff i dag: <b>{hits_today}</b>",
        f"🖼 Bilder analysert totalt: <b>{images_analyzed}</b>  "
        f"(🟢 grønne: {images_green})",
    ]

    if source_rows:
        lines += ["", "📡 Topp 6 kilder (siste 24t):"]
        for src, cnt in source_rows:
            lines.append(f"  • {src}: {cnt}")

    if errors_today > 20:
        lines += [f"", f"⚠️ {errors_today} feil (mest CFS 403) – ikke kritisk"]

    lines += ["", "🔍 Dybdesøk kjøres hvert 3. time automatisk."]

    tg.send_text("\n".join(lines))
    print(f"[{now}] Timestatistikk sendt. Runder={rounds_today}, Treff={hits_today}")


if __name__ == "__main__":
    main()
