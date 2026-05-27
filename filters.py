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
    PLAYER_NAMES = {
        "veigar", "nannskog", "allanzinho", "andresen",
        "kjønsberg", "kjoensberg", "belsvik", "rushfeldt",
        "eftevaag", "leonhardsen", "bjørnebye", "thorstvedt",
        "lydersen", "riseth", "fjørtoft", "bakircioglu",
        "kennedy", "christer george", "dorsin", "hagen",
        "by rise", "sollied",
    }
    required = [t.lower() for t in cfg.get("required_terms", [])]
    if not any(t in text for t in required):
        if not any(p in text for p in PLAYER_NAMES):
            return False, 0, "mangler stabæk"

    # ── 2. Sjekk grønne ermer FØR alt annet ────────────────────────────
    _GREEN        = ("grønn", "grønne", "green", "grön", "grøn")
    _SLEEVE_WORDS = ("erme", "ermer", "sleeve", "sleeves", "ärmar", "ärm",
                     "ærmer", "ærme")
    _ARM_RE       = re.compile(r"\barm(er|ar)?\b")

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

    # ── 5. Send KUN grønne ermer ────────────────────────────────────────
    if not is_green_sleeve:
        return False, 0, "ikke grønne ermer"

    return True, score, reason_str
