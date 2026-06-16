import re
import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")

CHILD_INDICATORS = {
    "barn", "barnestørrelse", "junior", "kids", "youth",
    "116", "122", "128", "134", "140", "146", "152",
}

NEW_SEASON_PHRASES = {"ny sesong", "sesong 2024", "sesong 2025", "sesong 2026"}


def _text(ad: Dict) -> str:
    return (
        (ad.get("title") or "") + " " + (ad.get("description") or "")
    ).lower()


def evaluate(ad: Dict, cfg: Dict) -> Tuple[bool, int, str]:
    """
    Returns (keep, score, reason).
    score ≥ 5  → grønne ermer + år/merke = JACKPOT   (⭐⭐ i melding)
    score ≥ 3  → grønne ermer eller tydelig vintage   (⭐ i melding)
    score ≥ 1  → noe signal – sendes                  (► i melding)
    score == 0 → passerer hard-filter – sendes også   (· i melding)
    keep=False → hopp over (kun ny-sesong + barnestørrelser)
    """
    text = _text(ad)

    # ── 1. Required term (inkl. vanlige skrivfeil) ───────────────────────
    # Kun navn som er SÅ unike at de nesten garantert peker på Stabæk.
    # Vanlige etternavn (Kennedy, Riseth, Thorstvedt, Bjørnebye osv.) er fjernet
    # fordi de gir false positives på Liverpool-, Norge- og Kongsvinger-drakter.
    PLAYER_NAMES = {
        "allanzinho",       # brasiliansk – ekstremt unik Stabæk-legende
        "bakircioglu",      # Kennedy Bakircioglu – ekstremt unik
        "nannskog",         # Martin Nannskog – svært Stabæk-spesifikk
        "veigar",           # Veigar Páll Gunnarsson – Islands/Stabæk-ikon
        "kjønsberg",        # Rune Kjønsberg
        "kjoensberg",       # skrivemåte uten æ
        "belsvik",          # Pål Belsvik
        "christer george",  # full navn – unikt nok
    }
    required = [t.lower() for t in cfg.get("required_terms", [])]
    if not any(t in text for t in required):
        if not any(p in text for p in PLAYER_NAMES):
            return False, 0, "mangler stabæk"

    # ── 2. Sjekk grønne ermer FØR alt annet ────────────────────────────
    _GREEN        = ("grønn", "grønne", "green", "grön", "grøn",
                     "groene", "groen")                          # + nederlandsk
    _SLEEVE_WORDS = ("erme", "ermer", "erm",                    # norsk
                     "sleeve", "sleeves",                        # engelsk
                     "ärmar", "ärm",                            # svensk
                     "ærmer", "ærme",                           # dansk
                     "mouwen", "mouw",                          # nederlandsk
                     "panel",                                    # eng beskrivelse
                     )
    _ARM_RE       = re.compile(r"\barm(er|ar|s)?\b")            # arm/armer/armar/arms

    has_green  = any(w in text for w in _GREEN)
    has_sleeve = any(w in text for w in _SLEEVE_WORDS) or bool(_ARM_RE.search(text))
    is_green_sleeve = has_green and has_sleeve

    # ── 3. Hard excludes – grønne ermer passerer ALLTID ─────────────────
    if not is_green_sleeve:
        for phrase in NEW_SEASON_PHRASES:
            if phrase in text:
                return False, 0, f"ny-sesong ({phrase})"

        exclude = [t.lower() for t in cfg.get("exclude_year_terms", [])]
        if any(t in text for t in exclude):
            is_collector = any(
                w in text for w in ("retro", "vintage", "gammel", "original",
                                    "signert", "signed", "matchworn", "match worn")
            )
            if not is_collector:
                return False, 0, "ny-sesong årstall"

    # ── 4. Children's sizes ─────────────────────────────────────────────
    if not cfg.get("include_children", False):
        if any(c in text.split() for c in CHILD_INDICATORS):
            is_collector = any(
                w in text for w in ("retro", "vintage", "original", "gammel",
                                    "signert", "signed")
            ) or is_green_sleeve
            if not is_collector:
                return False, 0, "barnestørrelse"

    # ── 5. Scoring ───────────────────────────────────────────────────────
    score = 0
    reasons = []

    # 🟢 GRØNNE ERMER – høyeste prioritet, dominerer alt annet
    if is_green_sleeve:
        score += 10
        reasons.append("🟢 GRØNNE ERMER")
    elif has_green:
        score += 3
        reasons.append("grønn farge")

    # High-relevance terms
    high_terms = [t.lower() for t in cfg.get("high_relevance_terms", [])]
    matched = [t for t in high_terms if t in text]
    score += len(matched)
    if matched:
        reasons.append(", ".join(matched[:4]))

    # Årstall – reager på ALLE år, ikke bare vintage-range
    years_in_text = [int(y) for y in _YEAR_RE.findall(text)]
    vintage_from = cfg["vintage_year_range"]["from"]
    vintage_to   = cfg["vintage_year_range"]["to"]
    has_vintage_year = any(vintage_from <= y <= vintage_to for y in years_in_text)
    has_any_year     = bool(years_in_text)

    if has_vintage_year:
        score += 2
        matched_years = [y for y in years_in_text if vintage_from <= y <= vintage_to]
        reasons.append(f"år {matched_years[0]}")
    elif has_any_year:
        score += 1
        reasons.append(f"år {years_in_text[0]}")

    reason_str = " | ".join(reasons) if reasons else "Stabæk-drakt"

    # ── 5. Send grønne ermer, vintage-årstall eller vintage-ord ─────────
    VINTAGE_WORDS = {
        "vintage", "retro", "gammel", "klassisk", "original",
        "sjelden", "rare", "diadora", "umbro", "kelme",
        "matchworn", "match worn", "match-worn",
        "signert", "signed", "autograph",
        "player issue", "player worn", "spillerdrakt", "kampdrakt",
        "hjemmedrakt", "bortedrakt",
        "90s", "90-tall", "1990s",
    }
    has_vintage_word = any(w in text for w in VINTAGE_WORDS)

    if not is_green_sleeve and not has_vintage_year and not has_vintage_word:
        return False, 0, "ingen grønn arm, årstall eller vintage-ord"

    return True, score, reason_str
