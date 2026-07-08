"""
Generelt websøk via DuckDuckGo HTML.

Brukes for å fange opp små sider/markedsplasser som ikke har sin egen
scraper – fora, små nettbutikker, blogger, sociale medier osv.

Strategi:
  - Søker via html.duckduckgo.com (ingen API-nøkkel nødvendig)
  - Filtrerer bort domener vi allerede har egne skrapere for
    (unngår duplikater)
  - Filtrerer bort åpenbart irrelevante domener (Wikipedia, nyheter osv.)
  - Returnerer titler + URL-er som «annonser» – filteret rydder resten
"""

import logging
import re
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as cf

logger = logging.getLogger(__name__)

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,no;q=0.8",
}

# Domener vi allerede skraper – hopp over (unngå duplikater)
_OWN_DOMAINS = {
    "finn.no", "tise.com", "forzasecondhand.no", "draktgata.no",
    "ebay.co.uk", "ebay.de", "ebay.com", "ebay.nl", "ebay.fr",
    "vinted.com", "vinted.no", "vinted.de", "vinted.co.uk",
    "tradera.com", "blocket.se", "dba.dk", "depop.com",
    "classicfootballshirts.co.uk", "vintagefootballshirts.com",
    "reddit.com", "old.reddit.com",
    "catawiki.com", "thefootballidiots.com",
    "marktplaats.nl", "grailed.com", "cultkits.com",
    "classickits.no", "532.no",
}

# Domener som åpenbart ikke selger drakter (nyheter, oppslagsverk, sosialt)
_BLOCKED_DOMAINS = {
    "wikipedia.org", "no.wikipedia.org", "en.wikipedia.org",
    "stabak.no", "stabakbutikken.no",          # offisielle, kun moderne
    "unisportstore.no", "antonsport.no",       # kun moderne nye drakter
    "youtube.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "vg.no", "dagbladet.no", "nrk.no", "tv2.no", "aftenposten.no",
    "transfermarkt.com", "soccerway.com", "fbref.com", "uefa.com",
    "amazon.com", "amazon.co.uk", "amazon.de",
    "google.com", "duckduckgo.com", "bing.com",
    "grokipedia.com", "footballwiki.com",
    "github.com", "githubusercontent.com",     # vårt eget repo
    "espn.com", "espnfc.com", "skysports.com", "bbc.com", "bbc.co.uk",
    "linkedin.com", "tiktok.com", "pinterest.com",
    # Informasjons- og statistikksider (ikke butikker)
    "footballkitarchive.com", "footballdatabase.eu", "worldfootball.net",
    "nationalfootballteams.com", "soccerbase.com", "fotmob.com",
    "colours-of-football.com", "footballshirtculture.com",
    "footballshirts.com", "footballshirtcollective.com",   # informasjonsblogg
    "sofascore.com", "flashscore.com", "besoccer.com", "globalsportsarchive.com",
    # Bildebanker
    "alamy.com", "gettyimages.com", "shutterstock.com", "istockphoto.com",
    "imago-images.com", "dreamstime.com",
    # Generisk print-on-demand (ikke ekte vintage)
    "redbubble.com", "spreadshirt.com", "zazzle.com", "teespring.com",
    "teepublic.com",
    # Norsk presse / blogger
    "sportsbibelen.no", "altomstabek.no", "kreativtforum.no",
    "nettavisen.no", "fotball.no", "ndla.no",
    # Andre nyhets-/oppslagsverk
    "footballia.net", "fotbollskanalen.se", "ronaldo7.net",
    "weltfussball.de", "footballorgin.com", "footballfanbase.com",
    "thesportsdb.com",
    "snl.no", "lokalhistoriewiki.no", "norskfodbold.dk",
    "fotballmuseet.no", "stat.no",
    "footballhistory.org", "flickr.com", "flickr", "datencenter.dfb", "dfb.de",
}

# Substrenger som blokkeres uansett TLD (transfermarkt.com/.co.uk/.us osv.)
_BLOCKED_SUBSTRINGS = {
    # Statistikk / oppslagsverk
    "transfermarkt", "wikiwand", "playmakerstats", "tribuna",
    "familysearch", "ancientfaces", "researchgate", "forebears",
    "stcroixlandmarks", "twitch", "aliexpress", "soccerway",
    "statscrew", "fotmob", "fbref", "uefa", "fifa.com",
    "sofascore", "flashscore", "besoccer", "globalsports",
    "national-football-teams", "fotball-databaser",
    "footystats", "onefootball", "worldfootball", "fandom.com",
    "footballwiki", "wikipedia", "sportsreference",
    "stb.guru",   # Stabæk fan-blogg, ikke salg
    # Flere stats-sider funnet i siste skann
    "mondefootball", "weltfussball", "wildstat", "whoscored",
    "soccer24", "footlive", "forebet", "fichajes", "wikidata",
    "leagueofgraphs", "leagueoflegends", "deviantart",
    "stabakdata", "stabecksales", "thestabeckgroup",
    "youthscout1ng", "substack",
    # Reise- og naturvern (tilfeldige stedsnavn-treff)
    "tripadvisor", "trip.com", "mapcarta", "nationalzoo",
    "smconservation", "le.ac.uk", "zoominfo",
    # Nasjonal infrastruktur og kommune
    "banenor", "baerum.kommune", "ruv.is", "kristiansundbk",
    # Aktørsider / personnavn
    "jaredstabach", "belsvikelektro", "roislandco",
    "listafirme", "stabech.ro",
    # Svenske presse
    "hant.se", "familjeliv", "aftonbladet",
    # Norske artikler / blogger
    "wikisida.no", "trikotfc",
    # Norsk presse
    "budstikka", "altomstabek", "kreativtforum", "sportsbibelen",
    "nettavisen", "vg.no", "dagbladet", "nrk.no", "aftenposten",
    "tv2.no", "fotball.no",
    # Flere stats / genealogi
    "fctables", "futbol24", "scores24", "statarea",
    "ancestry", "myheritage", "geni.com",
    # Moderne fan-butikker (Stabæk siden 2018+)
    "unisportstore", "antonsport", "stabakbutikken", "stabak.no",
}


class WebSearchScraper:
    def __init__(self):
        self.session = cf.Session(impersonate="safari17_0")
        self.session.headers.update(_HEADERS)

    def search(self, keyword: str) -> List[Dict]:
        try:
            r = self.session.get(_DDG_URL, params={"q": keyword}, timeout=20)
            r.raise_for_status()
        except Exception as exc:
            logger.warning("WebSearch feil for '%s': %s", keyword, exc)
            return []

        soup = BeautifulSoup(r.text, "lxml")
        ads = []
        seen_urls = set()
        for result in soup.select("div.result, div.web-result"):
            ad = self._result_to_ad(result, seen_urls)
            if ad:
                ads.append(ad)
        logger.info("WebSearch '%s': %d treff", keyword, len(ads))
        return ads

    def _result_to_ad(self, result, seen_urls) -> Optional[Dict]:
        link = result.select_one("a.result__a, a.result-link")
        if not link:
            return None
        href = link.get("href", "")
        # DDG bruker redirect-URLer: /l/?uddg=ENCODED_URL
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            href = unquote(m.group(1))
        if not href.startswith("http"):
            return None

        try:
            host = urlparse(href).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
        except Exception:
            return None

        # Hopp over egne domener og blokkerte (exact match + suffix)
        for blocked in _OWN_DOMAINS | _BLOCKED_DOMAINS:
            if host == blocked or host.endswith("." + blocked):
                return None
        # Blokkér substreng-baserte støy-domener (alle TLDs)
        for sub in _BLOCKED_SUBSTRINGS:
            if sub in host:
                return None

        if href in seen_urls:
            return None
        seen_urls.add(href)

        title = link.get_text(" ", strip=True)
        if not title:
            return None

        # KRITISK: websøk gir ofte URLer hvor SNIPPETEN inneholder Stabæk
        # men selve siden er om noe helt annet (kommentar, intervju, bilde-
        # caption osv.). Krev derfor Stabæk/spillernavn i TITTELEN, ellers
        # blir det 80+ falske treff.
        _STAB_PAT = re.compile(r"stab[æabek]+", re.I)
        _PLAYER_PAT = re.compile(
            r"(allanzinho|bakircioglu|nannskog|veigar|kjønsberg|kjoensberg"
            r"|belsvik|lambech|christer george)",
            re.I,
        )
        if not _STAB_PAT.search(title) and not _PLAYER_PAT.search(title):
            return None

        snippet_el = result.select_one(".result__snippet, .result-snippet")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

        # ID fra domene+sti UTEN query/fragment: samme side gir samme ID
        # uansett hvilket søk som fant den (ellers re-varsles samme side under
        # hvert av de ~190 dypsøk-ordene med litt ulik URL).
        _pp = urlparse(href)
        _norm = (_pp.netloc + _pp.path).lower().rstrip("/")
        ad_id = "web_" + re.sub(r"[^a-z0-9]+", "_", _norm)[:80]

        return {
            "id":          ad_id,
            "source":      f"web:{host}",
            "title":       title[:200],
            "price":       "Se nettsiden",
            "url":         href,
            "image_url":   None,
            "description": snippet[:300],
        }
