import logging
import requests
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = str(chat_id)

    def _post(self, method: str, payload: dict) -> bool:
        url = _API.format(token=self.token, method=method)
        try:
            r = requests.post(url, json=payload, timeout=15)
            if not r.ok:
                logger.warning("Telegram %s feilet: %s", method, r.text[:200])
            return r.ok
        except requests.RequestException as exc:
            logger.error("Telegram-feil: %s", exc)
            return False

    def send_text(self, text: str) -> bool:
        return self._post("sendMessage", {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        })

    def send_ad(self, ad: Dict, score: int = 0, match_reason: str = "") -> bool:
        source_label = {"finn.no": "Finn.no", "ebay.co.uk": "eBay UK",
                        "ebay.de": "eBay DE"}.get(ad.get("source", ""), ad.get("source", ""))

        star = "⭐ " if score >= 2 else ""
        green_flag = "🟢 GRØNNE ERMER!" if "grønne ermer" in match_reason else ""

        caption_parts = [
            f"{star}<b>{ad.get('title', 'Ukjent tittel')}</b>",
        ]
        if green_flag:
            caption_parts.append(green_flag)

        price = ad.get("price", "")
        if price:
            caption_parts.append(f"💰 <b>{price}</b>")

        caption_parts.append(f"📍 {source_label}")

        if match_reason:
            caption_parts.append(f"<i>Treff: {match_reason}</i>")

        url = ad.get("url", "")
        if url:
            caption_parts.append(f'<a href="{url}">👉 Se annonsen</a>')

        caption = "\n".join(caption_parts)

        image_url = ad.get("image_url")
        if image_url:
            ok = self._post("sendPhoto", {
                "chat_id": self.chat_id,
                "photo": image_url,
                "caption": caption,
                "parse_mode": "HTML",
            })
            if ok:
                return True
            # Photo failed – fall back to text message
            logger.debug("sendPhoto feilet, sender tekstmelding i stedet")

        return self.send_text(caption)

    def verify_connection(self) -> bool:
        """Test that token and chat_id work."""
        url = _API.format(token=self.token, method="getMe")
        try:
            r = requests.get(url, timeout=10)
            if r.ok:
                name = r.json().get("result", {}).get("username", "?")
                logger.info("Telegram OK – bot: @%s", name)
                return True
            logger.error("Telegram getMe feilet: %s", r.text[:200])
        except requests.RequestException as exc:
            logger.error("Kan ikke nå Telegram: %s", exc)
        return False
