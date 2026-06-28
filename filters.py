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

    # ── 0. Etterlysninger («ønskes kjøpt») er IKKE til salgs ────────────
    # Funn 2026-06-28: «Stabæk drakt med grønn arm, 3000 kr» SÅ ut som
    # gralen til salgs, men var en KJØPER som lette etter den. Slike
    # annonser skal ikke varsles som funn – du kan ikke kjøpe dem.
    _WANTED = (
        "ønskes kjøpt", "ønskes kjøp", "ønskes byttet", "ønskes:",
        "på jakt etter", "jakter på", "ser etter en", "leter etter en",
        "ønsker å kjøpe", "vil kjøpe", "kjøpes!", "kjøpes.", "kjøpes ",
        "wanted", "want to buy", "wtb", "looking for", "in search of",
    )
    if any(w in text for w in _WANTED):
        return False, 0, "etterlysning (noen vil KJØPE, ikke selge)"

    # ── 1. Required term (inkl. vanlige skrivfeil) ───────────────────────
    # Kun navn som er SÅ unike at de nesten garantert peker på Stabæk.
    # Vanlige etternavn (Kennedy, Riseth, Thorstvedt, Bjørnebye osv.) er fjernet
    # fordi de gir false positives på Liverpool-, Norge- og Kongsvinger-drakter.
    # Unike spillernavn – peker nesten garantert på Stabæk alene.
    PLAYER_NAMES = {
        "alanzinho",        # brasiliansk legende – VANLIGSTE stavemåte (enkel-L)
        "allanzinho",       # alternativ stavemåte (dobbel-L)
        "nannskog",         # Martin Nannskog – svært Stabæk-spesifikk
        "kjønsberg",        # Rune Kjønsberg
        "kjoensberg",       # skrivemåte uten æ
        "belsvik",          # Pål Belsvik
        "lambech",          # bekreftet 2026-05-30: Adidas Stabæk JF 2001 #10
    }
    # Tvetydige navn – har sterk ANNEN betydning. Teller KUN sammen med
    # Stabæk/Norge-kontekst (ellers fanger de League of Legends «Veigar»,
    # Panini Sverige «Bakircioglu» osv.).
    AMBIGUOUS_PLAYERS = {
        "veigar",           # = League of Legends-figur
        "bakircioglu",      # spilte for Sverige – Panini Sverige-klistremerker
        "christer george",  # generisk navn
    }
    _NORDIC_CTX = ("stab", "norway", "norge", "norwegen", "norsk", "norvegia",
                   "eliteserien", "tippeligaen")
    # SPONSOR_NAMES-bypass FJERNET – Kärcher er en ekte produktprodusent
    # som lager grønne trykkvaskere/rengjøringsmidler. Bypass-en skapte
    # 100+ falske treff («Kärcher K2 Hochdruckreiniger» osv.). Sponsorer
    # blir fortsatt boostet hvis kombinert med «Stabæk» via config-søkene
    # ("Stabaek Karcher" som søkeord) og høyt-relevans-termer.
    required = [t.lower() for t in cfg.get("required_terms", [])]
    _has_required = any(t in text for t in required)
    _has_player   = any(p in text for p in PLAYER_NAMES)
    # Tvetydige navn teller bare med nordisk/Stabæk-kontekst i teksten
    if not _has_player and any(p in text for p in AMBIGUOUS_PLAYERS):
        if any(ctx in text for ctx in _NORDIC_CTX):
            _has_player = True
    if not (_has_required or _has_player):
        return False, 0, "mangler stabæk"

    # ── 1a. «stabak»-only er for løst – krever fotball-kontekst ─────────
    # «stabak» (uten æ OG uten e) matcher DJ Stabak (vinyl), «STAY BACK»-
    # skilt, tilfeldige etternavn osv. «stabæk», «stabbæk» og «stabaek»
    # (med e) er unike nok alene – slipper gjennom uten ekstra krav.
    # Streng-match: «stabæk», «stabbæk», «stabaek», «stabækk», «stabekk»,
    # «stabæck», «stabeck» – alle med æ ELLER e ELLER dobbelt k = unike nok.
    _has_strict_stab = bool(re.search(
        r"\bstab(?:æk|bæk|aek|ækk|ekk|æck|eck|ech)\b", text
    ))
    if not _has_strict_stab and _has_required and not _has_player:
        _FOOTBALL_CTX = {
            "drakt", "trøye", "jersey", "shirt", "trikot", "tröja", "trøje",
            "fotball", "football", "soccer", "voetbal", "fodbold", "fußball",
            "if ", " if", "fotballklubb", "fc ", " fc", "klubb",
            "sponsor", "hjemmedrakt", "bortedrakt", "kit",
        }
        if not any(w in text for w in _FOOTBALL_CTX):
            return False, 0, "stabak uten fotball-kontekst"

    # ── 1b. Spillernavn-bypass krever drakt-signal ───────────────────────
    # Hvis treffet kom via spillernavn (ikke required_terms), må teksten
    # inneholde et drakt-ord – fanger bøker/sanger/album om spillere.
    # Eks: "FINNS DET ÄGG FINNS DET HOPP Rune Belsvik 1988" → ingen drakt → blokkert.
    if not _has_required and _has_player:
        _JERSEY_WORDS = {
            "drakt", "trøye", "jersey", "shirt", "trikot",
            "tröja", "trøje", "voetbalshirt",
            "fotballdrakt", "bortedrakt", "hjemmedrakt",
        }
        if not any(w in text for w in _JERSEY_WORDS):
            return False, 0, "spillernavn men ingen drakt"

    # ── 1c. Hard-filter ikke-drakt merch (globalt) ──────────────────────
    # Autografkort, skjerf, gensere, pins, fotballkort osv. fanges her
    # uavhengig av score. Sjekker TITTELEN – ikke beskrivelsen.
    _title_lc_g = (ad.get("title") or "").lower()
    _MERCH_SIGNALS = {
        # Samlerobjekter
        "autografkort", "autograf-kort", "samlekort", "fotballkort",
        "autograf",  # «div. Stabæk autografer» osv.
        # Programmer / publikasjoner / billetter / bøker / postkort
        "programblad", "kampprogram", "program ", "programme",
        "billett", "ticket", "kortstokk", "stickers",
        "bok ", "bok.", "historikk", "vinyl", "maxi 12", " 12\"",
        " 7\"", " lp", "ep ", "cd ", "dvd ", " dvd",
        "postcard", "postkort", "rppc", "ansichtskarte",
        # Tilfeldige navne-kollisjoner
        "license plate", "vanity plate", "stay back",
        "stabekk skole", "stabekk school",
        # (skjerf på flere språk fjernet – du vil ha dem)
        # Hodeplagg (skjerf er ønsket – ikke blokker)
        " lue", "lue ", "caps ", " caps",
        # Plakater / bilder
        "plakat", "poster", "bilde ",
        # Andre klesplagg som IKKE er drakt (matchdrakt)
        "skole genser", "skolegenser", "college genser", "vindjakke",
        "treningsgenser", "hettegenser",
        "treningstrøye", "treningsdrakt", "treningsoverall",
        "training top", "training trikot", "training kit",
        "trainingsanzug", "allenamento", "trainings",
        "shorts", "sokker", "sokk ", "sko ",
        # Macron = Stabæks moderne (2018+) leverandør – ALDRI grailen
        "macron",
        # Pins / merker
        "pins", "pin ", "buttons", "kniv",
        # Rengjøring (Kärcher!)
        "rengjøring", "tepperens", "gulvvasker", "trykkvasker",
        "høytrykk", "højtryk", "hochdruck", "cleaner",
        "hagespyler", "vacuum", "støvsuger",
    }
    _JERSEY_TITLE_G = {
        "drakt", "trøye", "jersey", "shirt",
        "fotballdrakt", "bortedrakt", "hjemmedrakt",
        "trikot", "tröja", "trøje", "voetbalshirt",
    }
    if (any(w in _title_lc_g for w in _MERCH_SIGNALS)
            and not any(w in _title_lc_g for w in _JERSEY_TITLE_G)):
        return False, 0, "ikke-drakt merch"

    # ── 1d. HARD-BLOKK: alltid-moderne markører ─────────────────────────
    # Macron er Stabæks leverandør fra 2018+ – ALDRI grailen, uansett.
    # (NB: «template» fjernet 2026-06-04 – det er en VINTAGE-betegnelse
    # for Diadora/Umbro-design som flere klubber brukte; Halvor kjøpte
    # nettopp en ekte Stabæk 1997 home template.)
    _ALWAYS_MODERN = {"macron", "macron's", "concept kit"}
    if any(w in _title_lc_g for w in _ALWAYS_MODERN):
        return False, 0, "alltid-moderne (macron)"

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

    # ── 2b. Grønne ermer deaktivert for ikke-drakt gjenstander ──────────
    # Fanziner, lydbøker og lignende KAN nevne «grønne ermer» i teksten
    # uten å VÆRE en drakt. Vi sjekker TITTELEN (ikke beskrivelsen) for
    # å unngå at fanzine-beskrivelser som nevner drakten blokkerer seg selv.
    if is_green_sleeve:
        _title_lc = (ad.get("title") or "").lower()
        _NON_JERSEY_SIGNALS = {
            "lydbok", "audiobook",
            "fanzine", "fanzin", "frekkazin", "foldzin",
            "samlekort", "programblad", "kampprogram",
            "plakat", "poster", "hefte", "magasin",
            " cd", "cd:", "dvd ", " dvd",
        }
        _JERSEY_TITLE_SIGNALS = {
            "drakt", "trøye", "jersey", "shirt",
            "fotballdrakt", "bortedrakt", "hjemmedrakt",
            "trikot", "tröja", "trøje", "voetbalshirt",
        }
        _has_non_jersey   = any(w in _title_lc for w in _NON_JERSEY_SIGNALS)
        _has_jersey_title = any(w in _title_lc for w in _JERSEY_TITLE_SIGNALS)
        if _has_non_jersey and not _has_jersey_title:
            is_green_sleeve = False
            has_green = False

    # ── 2c. Grønne ermer bare for drakter uten tydelig moderne årstall ──
    # En Stabæk-drakt fra 2021 er IKKE den vi leter etter.
    # Deaktiver GRØNNE ERMER-alarmen hvis eneste årstall er etter 2004.
    if is_green_sleeve:
        _all_years_early = [int(y) for y in _YEAR_RE.findall(text)]
        _has_modern_only = (
            any(y > 2004 for y in _all_years_early)
            and not any(1980 <= y <= 2004 for y in _all_years_early)
        )
        if _has_modern_only:
            is_green_sleeve = False
            has_green = False   # ikke gi «grønn farge»-poeng til moderne drakt

    # (2d-sponsor-sjekk fjernet – SPONSOR_NAMES-bypass droppet pga. false positives)

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
    # Årstall – beregnes først (trengs for grail-sjekken under)
    years_in_text = [int(y) for y in _YEAR_RE.findall(text)]
    vintage_from = cfg["vintage_year_range"]["from"]
    vintage_to   = cfg["vintage_year_range"]["to"]
    has_vintage_year = any(vintage_from <= y <= vintage_to for y in years_in_text)
    has_any_year     = bool(years_in_text)

    if is_green_sleeve:
        # ── GRALEN: vintage (1990–2004) + grønn arm = det vi LETER etter ──
        # Skill den fra moderne grønne Stabæk-drakter med egen topp-alarm.
        if has_vintage_year:
            score += 20
            reasons.append("🟢🏆 MULIG VINTAGE GRØNN ARM – sjekk bildet!")
        else:
            score += 10
            reasons.append("🟢 mulig grønne ermer – sjekk bildet")
    elif has_green:
        score += 3
        reasons.append("grønn farge")

    # High-relevance terms
    high_terms = [t.lower() for t in cfg.get("high_relevance_terms", [])]
    matched = [t for t in high_terms if t in text]
    score += len(matched)
    if matched:
        reasons.append(", ".join(matched[:4]))

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
        "90s", "90-tall", "1990s",
    }
    has_vintage_word = any(w in text for w in VINTAGE_WORDS)

    # ── Bekreftet Stabæk-DRAKT slipper ALLTID gjennom ───────────────────
    # En ekte Stabæk-drakt er sjelden nok til at den skal varsles uansett
    # årstall – også moderne. (Tidligere ble «Stabæk 2008 home» stille
    # droppet her, så brukeren gikk glipp av drakter.) Grønn-arm/vintage
    # scorer fortsatt høyere; dette er bare et lavprioritert ►-varsel.
    _JERSEY_WORDS_FINAL = {
        "drakt", "trøye", "jersey", "shirt", "trikot", "tröja", "trøje",
        "fotballdrakt", "hjemmedrakt", "bortedrakt", "keeperdrakt",
        "maillot", "camiseta", "maglia", "voetbalshirt",
        # Kit-type-ord (Draktgata/butikker bruker «Stabæk 2008 home» uten
        # ordet «drakt») – kombinert med påkrevd «stabæk» = trygt drakt-signal
        "home", "away", "third", "hjemme", "borte", "tredje",
        " gk", "gk ", "keeper", "goalkeeper", "heimtrikot", "auswärts",
    }
    _is_stabaek_jersey = _has_required and any(w in text for w in _JERSEY_WORDS_FINAL)

    if not is_green_sleeve and not has_vintage_year and not has_vintage_word:
        if _is_stabaek_jersey:
            # Slipp gjennom som lavprioritert – sikrer at INGEN Stabæk-drakt
            # blir stille droppet.
            if not reasons:
                reason_str = "Stabæk-drakt (moderne)"
            return True, max(score, 1), reason_str
        if _has_player:
            # Unikt spillernavn (f.eks. Alanzinho) uten eksplisitt drakt-ord
            # er nesten garantert en drakt/spiller-gjenstand – varsle.
            return True, max(score, 2), reason_str if reasons else "Stabæk-spiller"
        return False, 0, "ikke en Stabæk-drakt"

    return True, score, reason_str
