import os
import json
import threading
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Global skrivelås – serialiserer skriving fra de 23 parallelle skraper-
# trådene. Holder også in-memory-settet konsistent.
_WRITE_LOCK = threading.Lock()

# Beholdt for bakoverkompatibilitet (monitor.py importerer den). Med JSONL-
# lagringen kan filen aldri bli «korrupt», så markøren settes aldri lenger.
DB_RESET_MARKER = ".db_was_reset"


class Database:
    """Dedup-lager basert på en JSONL-fil (én JSON-annonse per linje).

    Hvorfor ikke SQLite: SQLite-filen tålte ikke å round-trippe gjennom
    GitHub Actions-cachen – den ble «database disk image is malformed»
    (never-used-pages) på HVER kjøring. Da bygde selvhelbredingen den på
    nytt og primet stille → boten ble effektivt stum. En ren tekstfil
    (JSONL) kan ikke bli malformed: vi laster den til et sett i minnet og
    APPENDER nye linjer. Ødelegges siste linje (avbrutt skriving) hopper vi
    bare over den ved innlasting – i verste fall re-varsles én annonse.
    """

    def __init__(self, path: str):
        # Lagre alltid som .jsonl uansett hva config sier (.db = gammel).
        if path.endswith(".db"):
            path = path[:-3] + ".jsonl"
        self.path = path
        self._seen: dict[tuple[str, str], dict] = {}
        self._load()
        # True hvis lageret var tomt ved oppstart → monitor kjører da én
        # STILLE runde (markerer alt sett uten å varsle) så vi ikke flommer
        # med hele eksisterende inventar første gang.
        self.was_empty = len(self._seen) == 0
        logger.info("Database klar: %s (%d annonser i basen)",
                    self.path, len(self._seen))

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        bad = 0
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    key = (str(r["id"]), r["source"])
                    self._seen[key] = r
                except Exception:
                    bad += 1
        if bad:
            logger.warning("%d uleselige linjer hoppet over i %s", bad, self.path)

    def _append(self, rec: dict) -> None:
        # Append er trygt: hele linjen skrives på én gang. Kalles under lås.
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def is_seen(self, ad_id: str, source: str) -> bool:
        return (str(ad_id), source) in self._seen

    def mark_seen(self, ad_id: str, source: str, title: str, url: str) -> None:
        key = (str(ad_id), source)
        with _WRITE_LOCK:
            if key in self._seen:
                return
            rec = {"id": str(ad_id), "source": source, "title": title or "",
                   "url": url or "", "seen_at": datetime.now().isoformat(timespec="seconds")}
            self._seen[key] = rec
            self._append(rec)

    def check_and_mark(self, ad_id: str, source: str, title: str, url: str) -> bool:
        """Atomisk: marker som sett og returner True hvis dette var nytt."""
        key = (str(ad_id), source)
        with _WRITE_LOCK:
            if key in self._seen:
                return False
            rec = {"id": str(ad_id), "source": source, "title": title or "",
                   "url": url or "", "seen_at": datetime.now().isoformat(timespec="seconds")}
            self._seen[key] = rec
            self._append(rec)
            return True

    def count(self) -> int:
        return len(self._seen)

    def recent(self, limit: int = 20) -> list:
        rows = sorted(self._seen.values(),
                      key=lambda r: r.get("seen_at", ""), reverse=True)
        return rows[:limit]
