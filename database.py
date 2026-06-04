import sqlite3
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path: str):
        self.path = path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        # timeout=30 = vent inntil 30 sek hvis databasen er låst (mange
        # parallelle skrapere kan konkurrere om skriving). Erstatter
        # «database is locked»-feilene.
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        # WAL-mode tillater flere lesere samtidig med én skriver,
        # og er mye mer tolerant mot parallell tilgang enn standard.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seen_ads (
                    id      TEXT NOT NULL,
                    source  TEXT NOT NULL,
                    title   TEXT,
                    url     TEXT,
                    seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id, source)
                )
            """)
            conn.commit()
        logger.debug("Database klar: %s", self.path)

    def is_seen(self, ad_id: str, source: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_ads WHERE id = ? AND source = ?",
                (str(ad_id), source),
            ).fetchone()
        return row is not None

    def mark_seen(self, ad_id: str, source: str, title: str, url: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seen_ads (id, source, title, url) VALUES (?, ?, ?, ?)",
                (str(ad_id), source, title or "", url or ""),
            )
            conn.commit()

    def check_and_mark(self, ad_id: str, source: str, title: str, url: str) -> bool:
        """Atomisk: marker som sett og returner True hvis dette var nytt.
        Trådsikker – rowcount=1 betyr at raden ble satt inn (ny annons)."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO seen_ads (id, source, title, url) VALUES (?, ?, ?, ?)",
                (str(ad_id), source, title or "", url or ""),
            )
            conn.commit()
            return cur.rowcount > 0

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM seen_ads").fetchone()[0]

    def recent(self, limit: int = 20) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, source, title, url, seen_at FROM seen_ads ORDER BY seen_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
