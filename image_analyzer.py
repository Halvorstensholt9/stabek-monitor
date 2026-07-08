"""
Bildeanalyse for grønne ermer.

Strategi (i prioritert rekkefølge):
  1. SQLite-cache  – returnerer lagret svar for kjente bilder
  2. Fargedeteksjon (PIL/Pillow) – teller grønne piksler, ingen API-nøkkel nødvendig
  3. Claude Vision  – brukes BARE hvis ANTHROPIC_API_KEY er satt (mer presis)

Fargedeteksjonen er kalibrert for den klassiske Stabæk-grønne erme-fargen:
  H 100-175° (grønn-til-turkis), S >35 %, V >25 %  (HSV-rom).
  Terskel: >1.5 % av pikslene i bildet er tydelig grønne.
"""

import base64
import io
import logging
import os
import sqlite3
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# v2: gammel image_cache.db var full av falske positive (farge-only).
# Nytt filnavn = tom cache → alt re-analyseres med Vision som dommer.
_CACHE_DB  = "image_cache_v2.db"
_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
_MODEL     = "claude-haiku-4-5"

# Fargekalibrering – Stabæk-grønnen er teal/turkis (H≈179°, RGB≈30,208,207)
# Innstillingene er bevisst romslige for å tåle skygger, dårlig lys og eldre bilder.
# Testet: holder seg over terskel ned til ~15 % lysstyrke (ekstremt mørke bilder).
_HUE_LOW   = 90    # nedre grense: ren grønn (IKKE gul/lime under 90)
_HUE_HIGH  = 185   # øvre grense: teal/turkis (IKKE rent blått over 185)
_SAT_MIN   = 0.25  # må være en tydelig grønn, ikke en blass gråtone/skygge
_VAL_MIN   = 0.15  # ikke nesten-svarte piksler
_THRESHOLD = 0.04  # minst 4 % av pikslene må treffe (forfilter; Vision bekrefter)
_SCAN_TOP  = 0.75  # analyser bare øverste 75 % av bildet – kutter bort gressbakgrunn


# ── SQLite-cache ─────────────────────────────────────────────────────────────

def _init_cache() -> None:
    conn = sqlite3.connect(_CACHE_DB)
    # Lagrer nå en SANNSYNLIGHET 0–100 (grål-score) pr bilde, ikke bare ja/nei.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS grail (
            url        TEXT PRIMARY KEY,
            score      INTEGER NOT NULL,
            checked_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def _get_cached(url: str) -> Optional[int]:
    try:
        conn = sqlite3.connect(_CACHE_DB)
        row = conn.execute(
            "SELECT score FROM grail WHERE url = ?", (url,)
        ).fetchone()
        conn.close()
        return int(row[0]) if row is not None else None
    except Exception:
        return None


def _set_cached(url: str, score: int) -> None:
    try:
        conn = sqlite3.connect(_CACHE_DB)
        conn.execute(
            "INSERT OR REPLACE INTO grail (url, score) VALUES (?, ?)",
            (url, int(score)),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Fargedeteksjon (PIL) ──────────────────────────────────────────────────────

def _rgb_to_hsv(r: int, g: int, b: int):
    """Konverter RGB (0-255) til HSV (H:0-360, S:0-1, V:0-1)."""
    r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
    cmax = max(r_, g_, b_)
    cmin = min(r_, g_, b_)
    diff = cmax - cmin
    v = cmax
    s = 0.0 if cmax == 0 else diff / cmax
    if diff == 0:
        h = 0.0
    elif cmax == r_:
        h = (60 * ((g_ - b_) / diff) % 360)
    elif cmax == g_:
        h = 60 * ((b_ - r_) / diff + 2)
    else:
        h = 60 * ((r_ - g_) / diff + 4)
    return h, s, v


def _color_detect_green(img_bytes: bytes) -> bool:
    """
    Returnerer True hvis bildet inneholder nok grønne piksler
    til at det sannsynligvis viser en grønn erme.
    Sampel hvert 6. piksel for hastighet.
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        width, height = img.size
        pixels = img.load()

        green_count = 0
        total = 0
        step = 6  # sample hvert 6. piksel

        # Analyser bare øverste 75 % av bildet – kutter bort gressbakgrunn
        # i bunnen av produktbilder (spillere på banen, stadion-bakgrunn osv.)
        scan_height = int(height * _SCAN_TOP)

        for x in range(0, width, step):
            for y in range(0, scan_height, step):
                r, g, b = pixels[x, y]
                h, s, v = _rgb_to_hsv(r, g, b)
                total += 1
                if _HUE_LOW <= h <= _HUE_HIGH and s >= _SAT_MIN and v >= _VAL_MIN:
                    green_count += 1

        ratio = green_count / total if total else 0
        logger.debug("🎨 Fargeanalyse: %.2f%% grønne piksler (terskel %.1f%%)",
                     ratio * 100, _THRESHOLD * 100)
        return ratio >= _THRESHOLD

    except ImportError:
        logger.debug("PIL ikke installert – fargeanalyse deaktivert")
        return False
    except Exception as exc:
        logger.debug("Fargeanalyse feil: %s", exc)
        return False


# ── Claude Vision (valgfri, mer presis) ──────────────────────────────────────

# Terskel: ≥ denne prosenten regnes som «grønn arm / mulig gral».
_GRAIL_THRESHOLD = 40

# Presis beskrivelse av gralen (verifisert mot Halvors referansebilder +
# ekte annonser 2026-07: grønn-arm-drakter scoret 75–85 %, vanlige blå/
# dame/moderne Stabæk-drakter 5–15 %).
_GRAIL_PROMPT = (
    "This is a product photo of a football/soccer shirt. I am hunting one specific "
    "vintage/retro STABÆK (Stabæk IF/JF, Norwegian) shirt. Identifying features:\n"
    "- BODY: blue and navy VERTICAL STRIPES (Inter-Milan-like).\n"
    "- KEY: ONE sleeve is GREEN/teal while the OTHER sleeve is blue (an asymmetric "
    "green arm), often with white adidas 3-stripes running down the green sleeve.\n"
    "- Usually adidas, usually long-sleeve; gold Stabæk crest with '1912'.\n"
    "Give the PROBABILITY from 0 to 100 that THIS shirt is that Stabæk blue-striped "
    "ONE-GREEN-SLEEVE shirt. A blue/striped shirt WITHOUT any green sleeve = LOW "
    "(under 30). A blue-striped shirt WITH one green/teal sleeve = HIGH (over 70). "
    "Ignore green logos/backgrounds/grass. Reply with ONLY an integer 0-100."
)


def _vision_grail_score(img_bytes: bytes, content_type: str) -> int:
    """Claude Vision → sannsynlighet 0–100 for at bildet er grål-drakta.
    -1 hvis ingen API-nøkkel eller feil."""
    if not _API_KEY:
        return -1
    try:
        import re as _re
        import anthropic
        img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
        client  = anthropic.Anthropic(api_key=_API_KEY)
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=8,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64",
                        "media_type": content_type, "data": img_b64}},
                    {"type": "text", "text": _GRAIL_PROMPT},
                ],
            }],
        )
        m = _re.search(r"\d+", msg.content[0].text)
        return min(100, int(m.group())) if m else -1
    except Exception as exc:
        logger.debug("Claude Vision feil: %s", exc)
        return -1


# ── Hoved-funksjon ───────────────────────────────────────────────────────────

def grail_probability(image_url: str) -> int:
    """Sannsynlighet 0–100 for at bildet viser Stabæk grønn-arm-gralen.
    Cache → fargeforfilter → Claude Vision. Uten API-nøkkel: grov 0/35 fra farge."""
    cached = _get_cached(image_url)
    if cached is not None:
        return cached

    try:
        r = httpx.get(image_url, timeout=20, follow_redirects=True)
        r.raise_for_status()
        img_bytes    = r.content
        content_type = r.headers.get("content-type", "image/jpeg").split(";")[0]
        if content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            content_type = "image/jpeg"
    except Exception as exc:
        logger.debug("Bilde-nedlasting feilet %s: %s", image_url[:60], exc)
        return 0

    # Billig fargeforfilter: ingen grønt i det hele tatt → svært lav sannsynlighet,
    # spar Vision-kallet. Ellers la Vision gi presis score.
    color_hint = _color_detect_green(img_bytes)
    if _API_KEY:
        score = _vision_grail_score(img_bytes, content_type) if color_hint else 5
        if score < 0:                       # Vision feilet – fall tilbake på farge
            score = 35 if color_hint else 5
    else:
        score = 35 if color_hint else 5     # ingen nøkkel: kun grovt fargesignal

    _set_cached(image_url, score)
    logger.info("🖼 Grål-score: %s → %d%% (farge=%s)",
                image_url.split("/")[-1][:50], score, "ja" if color_hint else "nei")
    return score


def has_green_sleeve(image_url: str) -> bool:
    """Bakoverkompatibel: True hvis grål-sannsynligheten er ≥ terskel."""
    return grail_probability(image_url) >= _GRAIL_THRESHOLD


# Initialiser cache ved import
try:
    _init_cache()
except Exception:
    pass
