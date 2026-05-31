"""
Sporings-følger for Lambech-drakten (og evt. andre forsendelser).

Sjekker Aftership/Grailed sin offentlige sporings-side. Sender Telegram-
varsel KUN ved statusendring (ingen spam). State lagres i tracking_state.json.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path

import yaml
from bs4 import BeautifulSoup
from curl_cffi import requests as cf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

ROOT       = Path(__file__).parent
STATE_FILE = ROOT / "tracking_state.json"
CONFIG     = yaml.safe_load((ROOT / "config.yaml").read_text())

# Forsendelser å følge: (etikett, sporings-URL)
SHIPMENTS = [
    {
        "id":      "lambech_2001",
        "label":   "Adidas Stabæk JF 2001 #10 Lambech",
        "url":     "https://grailed.aftership.com/LX045854596PL",
        "tracking_no": "LX045854596PL",
        "carrier": "Poczta Polska",
    },
]


def fetch_status(url: str) -> str:
    """Returner ren status-tekst fra Aftership-siden."""
    s = cf.Session(impersonate="safari17_0")
    r = s.get(url, timeout=25, allow_redirects=True)
    r.raise_for_status()
    text = BeautifulSoup(r.text, "lxml").get_text(" ", strip=True)

    # Aftership-siden viser sjekkpunkter på formen:
    #   "Checkpoint timezone May 30, 2026 12:19 PM The package has been
    #    picked up and is in transit."
    # Vi vil ha selve meldingen + dato i én linje.
    cp = re.search(
        r"Checkpoint timezone\s+"
        r"([A-Z][a-z]+ \d+,\s*\d{4}\s+\d+:\d+\s*[AP]M)\s+"
        r"(.+?)(?:\s+Posten|\s+Contact Us|\s+Last update|\s+Tracking history|$)",
        text,
    )
    if cp:
        when, what = cp.group(1).strip(), cp.group(2).strip()
        return f"{what} ({when})"

    # Fallback til kjente faseord
    for phrase in [
        "Delivered",
        "Out for delivery",
        "Available for pickup",
        "Customs clearance",
        "Arrived at destination",
        "In transit",
        "Picked up",
        "Awaiting shipment",
        "Your order has been prepared",
        "Order prepared",
        "Pending",
        "Exception",
        "Returned",
    ]:
        if phrase.lower() in text.lower():
            return phrase

    # Siste fallback: gammel regex (kan være rotete men bedre enn ingenting)
    m = re.search(
        r"(?:\+\d[\d\-\s]+|Poczta Polska|carrier|Carrier)\s+"
        r"(.+?)\s+(?:Check back later|Last update|Tracking history|Contact Us)",
        text,
    )
    if m:
        return re.sub(r"^\+?\d[\d\-\s]{6,}\s+", "", m.group(1).strip())
    return "Ukjent (parser-feil)"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def notify_telegram(text: str) -> None:
    tg = CONFIG["telegram"]
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg["bot_token"]
    chat  = os.environ.get("TELEGRAM_CHAT_ID")  or str(tg["chat_id"])
    import requests
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )


def main():
    state = load_state()
    for ship in SHIPMENTS:
        sid = ship["id"]
        try:
            current = fetch_status(ship["url"])
        except Exception as exc:
            logger.error("Feil ved henting av %s: %s", sid, exc)
            continue
        previous = state.get(sid, {}).get("status")
        logger.info("[%s] forrige=%r  ny=%r", sid, previous, current)

        if current != previous:
            if previous is None:
                msg = (
                    f"📦 <b>Sporing aktiv</b>\n"
                    f"{ship['label']}\n"
                    f"Status: <b>{current}</b>\n"
                    f"Fraktselskap: {ship['carrier']}\n"
                    f'<a href="{ship["url"]}">👉 Se sporing</a>'
                )
            else:
                msg = (
                    f"📦 <b>Status endret!</b>\n"
                    f"{ship['label']}\n"
                    f"<s>{previous}</s>\n"
                    f"→ <b>{current}</b>\n"
                    f'<a href="{ship["url"]}">👉 Se sporing</a>'
                )
            notify_telegram(msg)
            logger.info("Telegram-varsel sendt")
        else:
            logger.info("Ingen endring – ingen melding sendt")

        state[sid] = {
            "status":     current,
            "label":      ship["label"],
            "tracking_no": ship["tracking_no"],
            "carrier":    ship["carrier"],
            "url":        ship["url"],
        }
    save_state(state)


if __name__ == "__main__":
    main()
