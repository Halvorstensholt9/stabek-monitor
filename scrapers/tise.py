"""
Tise – norsk second-hand-app.

Tise er en SPA bak AWS WAF Bot Control – krever browser-automation
(Playwright med headless Chromium) for å løse JS-utfordringen.

Strategi:
  1. Hold ÉN browser-instans i live for hele monitorens levetid (lazy init).
  2. Første navigering løser WAF-utfordringen og setter aws-waf-token cookie.
  3. Påfølgende søk gjenbruker samme context og kjører raskt.
"""

import atexit
import logging
import re
import threading
import urllib.parse
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_BASE   = "https://tise.com"
_SEARCH = f"{_BASE}/search/tise"
_ITEM_RE = re.compile(r"/t/([A-Za-z0-9_-]{6,})")

# Modulen holder én singleton-browser for hele prosessens levetid.
_browser_lock = threading.Lock()
_playwright   = None
_browser      = None
_context      = None


def _ensure_browser():
    """Lazy-init av Playwright + headless Chromium. Idempotent og trådsikker."""
    global _playwright, _browser, _context
    if _context is not None:
        return _context
    with _browser_lock:
        if _context is not None:
            return _context
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Tise: Playwright ikke installert "
                         "(pip install playwright && playwright install chromium)")
            return None
        try:
            _playwright = sync_playwright().start()
            _browser = _playwright.chromium.launch(headless=True)
            _context = _browser.new_context(
                user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                            "Version/17.0 Safari/605.1.15"),
                locale="nb-NO",
                viewport={"width": 1280, "height": 800},
            )
            # Førstegangs-besøk for å løse WAF-utfordring og hente cookies
            page = _context.new_page()
            page.goto(f"{_BASE}/", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2_500)
            # Lukk cookie-modal (Accept) – ellers blokkerer den klikk på søk
            _dismiss_cookie_modal(page)
            page.close()
            logger.info("Tise: Playwright + Chromium klar (WAF-cookie hentet)")
        except Exception as exc:
            logger.error("Tise: kunne ikke starte browser: %s", exc)
            _close_browser()
            return None
        return _context


def _close_browser():
    global _playwright, _browser, _context
    try:
        if _context: _context.close()
    except Exception: pass
    try:
        if _browser: _browser.close()
    except Exception: pass
    try:
        if _playwright: _playwright.stop()
    except Exception: pass
    _context = _browser = _playwright = None


atexit.register(_close_browser)


def _dismiss_cookie_modal(page):
    """Klikk Accept/Aksepter i cookie-modalen hvis den vises. Idempotent."""
    try:
        # Tise oversetter UI etter locale – matcher både engelsk og norsk
        btn = page.get_by_role("button", name=re.compile(r"^(Accept|Aksepter)$", re.I))
        if btn.count() > 0:
            btn.first.click(timeout=3_000)
            page.wait_for_timeout(800)
    except Exception:
        pass


class TiseScraper:
    def search(self, keyword: str) -> List[Dict]:
        ctx = _ensure_browser()
        if ctx is None:
            return []
        page = None
        try:
            page = ctx.new_page()
            # Tises SPA respekterer ikke URL-search-param ved direkte navigasjon
            # (returnerer cached homepage-feed). Vi må bruke selve søkeboksen
            # for å trigge søk-state-en i React-routeren.
            page.goto(f"{_BASE}/", wait_until="domcontentloaded", timeout=25_000)
            page.wait_for_timeout(1_500)
            # Lukk cookie-modal i tilfelle den dukker opp på nytt
            try:
                page.evaluate("""() => {
                    const modal = document.querySelector('.ReactModal__Overlay--after-open');
                    if (!modal) return;
                    for (const b of modal.querySelectorAll('button')) {
                        const t = b.textContent.toLowerCase();
                        if (t.includes('accept') || t.includes('godta')) { b.click(); return; }
                    }
                }""")
                page.wait_for_timeout(500)
            except Exception:
                pass
            # Fyll søke-input og trykk Enter
            search_input = page.locator('input[type="search"]').first
            search_input.click(timeout=10_000)
            search_input.fill(keyword)
            page.keyboard.press("Enter")
            # Vent på at søkeresultater lastes
            page.wait_for_load_state("networkidle", timeout=20_000)
            page.wait_for_timeout(2_000)

            items = page.evaluate("""
                () => {
                  const out = [];
                  const links = document.querySelectorAll('a[href*="/t/"]');
                  const seen = new Set();
                  for (const a of links) {
                    const m = a.getAttribute('href').match(/^\\/t\\/([A-Za-z0-9_-]{6,})/);
                    if (!m) continue;
                    const id = m[1];
                    if (seen.has(id)) continue;
                    seen.add(id);
                    let card = a.closest('article') || a.closest('li') || a.parentElement;
                    const img = card?.querySelector('img');
                    const titleEl = card?.querySelector(
                      'h2, h3, [class*="title"], [class*="name"]'
                    );
                    const title = titleEl?.textContent?.trim()
                                  || img?.alt?.trim()
                                  || a.textContent?.trim();
                    const priceEl = card?.querySelector(
                      '[class*="price"], [data-test*="price"]'
                    );
                    out.push({
                      id,
                      title: title || '',
                      url: a.href,
                      img: img?.src || img?.dataset?.src || '',
                      price: priceEl?.textContent?.trim() || '',
                    });
                  }
                  return out;
                }
            """)

            ads = []
            for it in items:
                if not it.get("title"):
                    continue
                ads.append({
                    "id":          f"tise_{it['id']}",
                    "source":      "tise.com",
                    "title":       it["title"][:200],
                    "price":       it["price"] or "Se Tise",
                    "url":         it["url"],
                    "image_url":   it["img"] or None,
                    "description": "",
                })
            logger.info("Tise '%s': %d treff", keyword, len(ads))
            return ads

        except Exception as exc:
            logger.warning("Tise feil for '%s': %s", keyword, exc)
            return []
        finally:
            if page:
                try: page.close()
                except Exception: pass
