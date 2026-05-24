"""
Facebook Groups scraper.
Bruker facebook-scraper-biblioteket med dine innloggings-cookies.

Slik skaffer du cookies.txt (gjøres én gang):
  1. Installer nettleserutvidelsen "Get cookies.txt LOCALLY" i Chrome/Firefox
     Chrome: https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc
  2. Gå til facebook.com mens du er logget inn
  3. Klikk på utvidelse-ikonet → velg "Export cookies for this tab"
  4. Lagre filen som 'facebook_cookies.txt' i prosjektmappen

Merk: Cookies varer typisk noen uker–måneder. Når monitoren varsler om
"Facebook cookies utløpt", gjenta stegene over.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(
    r"(\d[\d\s.,]*)\s*(?:kr|krone[r]?|,-)",
    re.IGNORECASE,
)

try:
    from facebook_scraper import get_posts as _fb_get_posts
    from facebook_scraper.exceptions import (
        TemporarilyBanned,
        LoginRequired,
        NotFound,
    )
    _FB_OK = True
except ImportError:
    _FB_OK = False

    class TemporarilyBanned(Exception): pass
    class LoginRequired(Exception): pass
    class NotFound(Exception): pass


def _extract_price(text: str) -> Optional[str]:
    m = _PRICE_RE.search(text)
    if m:
        digits = re.sub(r"[\s]", "", m.group(1))
        return f"{digits} kr"
    return None


class FacebookScraper:
    def __init__(self, cookies_path: str, posts_per_group: int = 20):
        self.cookies_path = cookies_path
        self.posts_per_group = posts_per_group
        self._cookies_exist = Path(cookies_path).exists()

        if not _FB_OK:
            logger.warning(
                "facebook-scraper ikke installert. Kjør: pip3 install facebook-scraper"
            )
        elif not self._cookies_exist:
            logger.warning(
                "Facebook cookies-fil ikke funnet: %s  "
                "Les README.md → 'Sette opp Facebook' for instruksjoner.",
                cookies_path,
            )

    @property
    def ready(self) -> bool:
        return _FB_OK and self._cookies_exist

    def search_group(self, group_id: str) -> List[Dict]:
        """Henter de nyeste postene fra én Facebook-gruppe."""
        if not self.ready:
            return []

        # facebook-scraper bruker pages à ~10 poster
        pages = max(1, self.posts_per_group // 10)
        results = []

        try:
            for post in _fb_get_posts(
                account=str(group_id),
                group=True,
                pages=pages,
                cookies=self.cookies_path,
                timeout=30,
                options={"allow_extra_requests": False, "comments": False},
            ):
                ad = self._post_to_ad(post, group_id)
                if ad:
                    results.append(ad)

        except TemporarilyBanned:
            logger.warning(
                "Facebook sperret midlertidig tilgang. "
                "Vent noen timer og prøv igjen."
            )
        except LoginRequired:
            logger.error(
                "Facebook cookies er utløpt for gruppe '%s'. "
                "Eksporter nye cookies (se README) og erstatt facebook_cookies.txt.",
                group_id,
            )
        except NotFound:
            logger.error(
                "Facebook-gruppe '%s' ikke funnet. "
                "Sjekk at group_id i config.yaml er riktig.",
                group_id,
            )
        except Exception as exc:
            logger.error("Facebook gruppe '%s' uventet feil: %s", group_id, exc)

        logger.info("Facebook gruppe '%s': %d poster", group_id, len(results))
        return results

    def _post_to_ad(self, post: dict, group_id: str) -> Optional[Dict]:
        post_id = str(post.get("post_id") or "")
        if not post_id:
            return None

        text = (post.get("text") or post.get("post_text") or "").strip()
        if not text:
            return None

        # Første linje som tittel (maks 120 tegn)
        title = text.split("\n")[0][:120]

        price_str = _extract_price(text)
        if not price_str:
            # Prøv i delte data også
            price_amount = post.get("price") or post.get("listed_price")
            price_str = str(price_amount) if price_amount else "Se post for pris"

        images = post.get("images") or post.get("image") or []
        if isinstance(images, str):
            images = [images]
        img_url = images[0] if images else None

        url = post.get("post_url") or f"https://www.facebook.com/groups/{group_id}"

        return {
            "id": f"fb_{post_id}",
            "source": "facebook",
            "title": title,
            "price": price_str,
            "url": url,
            "image_url": img_url,
            "description": text,
        }
