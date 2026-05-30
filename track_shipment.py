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
    # Aftership-mønster: "...phone... <STATUS> Check back later..."
    m = re.search(
        r"(?:\+\d[\d\-\s]+|Poczta Polska|carrier|Carrier)\s+"
        r"(.+?)\s+(?:Check back later|Last update|Tracking history|Contact Us)",
        text,
    )
    if m:
        status = m.group(1).strip()
        # Fjern ledende telefonnummer hvis regex tok det med
        status = re.sub(r"^\+?\d[\d\-\s]{6,}\s+", "", status).strip()
        return status
    # Fallback: led etter kjente status-fraser
    for phrase in [
        "Delivered",
        "Out for delivery",
        "In transit",
        "Awaiting shipment",
        "Order prepared",
        "Your order has been prepared",
        "Pending",
        "Exception",
        "Returned",
    ]:
        if phrase.lower() in text.lower():
            return phrase
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
