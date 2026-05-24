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
    score ≥ 1  → high-confidence vintage match  (★ in message)
    score == 0 → generic Stabæk listing        (no star, still sent)
    keep=False → skip entirely
    """
    text = _text(ad)

    # ── 1. Required term ────────────────────────────────────────────────
    required = [t.lower() for t in cfg.get("required_terms", [])]
    if not any(t in text for t in required):
        return False, 0, "mangler 'stabæk'"

    # ── 2. Hard excludes: clearly new-season jerseys ─────────────────────
    exclude_year_terms = [t.lower() for t in cfg.get("exclude_year_terms", [])]
    for phrase in NEW_SEASON_PHRASES:
        if phrase in text:
            return False, 0, f"ny-sesong ({phrase})"

    years_in_text = [int(y) for y in _YEAR_RE.findall(text)]
    has_modern_year = any(y >= 2010 for y in years_in_text)
    has_vintage_year = any(
        cfg["vintage_year_range"]["from"] <= y <= cfg["vintage_year_range"]["to"]
        for y in years_in_text
    )

    if has_modern_year and not has_vintage_year:
        is_vintage_labelled = any(
            w in text for w in ("retro", "vintage", "gammel", "original", "klassisk")
        )
        if not is_vintage_labelled:
            return False, 0, "nyere årstall uten retro-label"

    # ── 3. Children's sizes ─────────────────────────────────────────────
    if not cfg.get("include_children", False):
        if any(c in text.split() for c in CHILD_INDICATORS):
            is_collector = any(
                w in text for w in ("retro", "vintage", "original", "gammel")
            )
            if not is_collector:
                return False, 0, "barnestørrelse"

    # ── 4. Scoring ───────────────────────────────────────────────────────
    score = 0
    reasons = []

    # Green sleeves = jackpot
    if ("grønn" in text or "grønne" in text or "green" in text) and (
        "erme" in text or "ermer" in text or "sleeve" in text
    ):
        score += 3
        reasons.append("grønne ermer")

    high_terms = [t.lower() for t in cfg.get("high_relevance_terms", [])]
    matched = [t for t in high_terms if t in text]
    score += len(matched)
    if matched:
        reasons.append(", ".join(matched[:3]))

    if has_vintage_year:
        score += 2
        matched_years = [y for y in years_in_text if
                         cfg["vintage_year_range"]["from"] <= y <= cfg["vintage_year_range"]["to"]]
        reasons.append(f"år {matched_years[0]}" if matched_years else "vintage år")

    reason_str = " | ".join(reasons) if reasons else "generisk Stabæk-drakt"
    return True, score, reason_str
