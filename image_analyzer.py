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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS image_cache (
            url        TEXT PRIMARY KEY,
            has_green  INTEGER NOT NULL,
            checked_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def _get_cached(url: str) -> Optional[bool]:
    try:
        conn = sqlite3.connect(_CACHE_DB)
        row = conn.execute(
            "SELECT has_green FROM image_cache WHERE url = ?", (url,)
        ).fetchone()
        conn.close()
        return bool(row[0]) if row is not None else None
    except Exception:
        return None


def _set_cached(url: str, result: bool) -> None:
    try:
        conn = sqlite3.connect(_CACHE_DB)
        conn.execute(
            "INSERT OR REPLACE INTO image_cache (url, has_green) VALUES (?, ?)",
            (url, int(result)),
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

def _vision_detect_green(img_bytes: bytes, content_type: str) -> bool:
    """Bruker Claude Haiku Vision. Krever ANTHROPIC_API_KEY."""
    if not _API_KEY:
        return False
    try:
        import anthropic
        img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
        client  = anthropic.Anthropic(api_key=_API_KEY)
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": content_type,
                            "data": img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is a product photo of a football/soccer shirt. "
                            "I am looking for ONE very specific feature: the SLEEVES "
                            "(the arm fabric) must be a distinct GREEN or TEAL/turquoise "
                            "colour that clearly CONTRASTS with the main body/torso of "
                            "the shirt (e.g. white or blue body with green arms).\n"
                            "Do NOT count: green logos, sponsors, numbers, text, trim, "
                            "piping, collars, the background, grass, or a shirt that is "
                            "entirely one colour. The SLEEVE FABRIC itself must be green/teal "
                            "and differ from the body.\n"
                            "Answer YES only if you are confident the sleeves are green/teal "
                            "and contrast with the body. If unsure or if it is any other "
                            "pattern, answer NO. Reply with exactly YES or NO."
                        ),
                    },
                ],
            }],
        )
        return msg.content[0].text.strip().upper().startswith("YES")
    except Exception as exc:
        logger.debug("Claude Vision feil: %s", exc)
        return False


# ── Hoved-funksjon ───────────────────────────────────────────────────────────

def has_green_sleeve(image_url: str) -> bool:
    """
    Returnerer True hvis bildet viser en drakt med grønne ermer.
    Bruker cache → fargedeteksjon → Claude Vision (hvis nøkkel finnes).
    """
    # 1. Cache
    cached = _get_cached(image_url)
    if cached is not None:
        logger.debug("🖼 Cache: %s → %s",
                     image_url.split("/")[-1][:40], "grønn" if cached else "ikke grønn")
        return cached

    # 2. Last ned bilde
    try:
        r = httpx.get(image_url, timeout=20, follow_redirects=True)
        r.raise_for_status()
        img_bytes    = r.content
        content_type = r.headers.get("content-type", "image/jpeg").split(";")[0]
        if content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            content_type = "image/jpeg"
    except Exception as exc:
        logger.debug("Bilde-nedlasting feilet %s: %s", image_url[:60], exc)
        return False

    # 3. Fargedeteksjon = billig FORFILTER (ikke fasit). Sier den nei, er det
    #    nesten sikkert ingen grønn erme → vi sparer et Vision-kall.
    color_hint = _color_detect_green(img_bytes)

    # 4. Claude Vision er DOMMEREN. Et grønt piksel-treff betyr ingenting før
    #    Vision har bekreftet at det faktisk er ERMENE som er grønne/teal og
    #    kontrasterer med kroppen. Dette dreper de falske positive («GRØNN ARM»
    #    på ting som ikke er det). Uten API-nøkkel faller vi tilbake på det
    #    svake fargesignalet alene.
    if _API_KEY:
        result = _vision_detect_green(img_bytes, content_type) if color_hint else False
    else:
        result = color_hint

    _set_cached(image_url, result)
    logger.info(
        "🖼 Bildeanalyse: %s → farge=%s, dom=%s",
        image_url.split("/")[-1][:50],
        "grønn" if color_hint else "nei",
        "🟢 GRØNN ERM (bekreftet)" if result else "ingen grønn erm",
    )
    return result


# Initialiser cache ved import
try:
    _init_cache()
except Exception:
    pass
