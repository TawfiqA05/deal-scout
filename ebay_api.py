"""
Deal Scout ↔ eBay connection.
Handles: logging into eBay's API (OAuth2), searching comparable ACTIVE
listings, and pulling details from an eBay listing URL (via the official
API — no scraping).

In demo mode everything here returns made-up data and makes no network
calls, so it works without keys.
"""

import base64
import logging
import os
import random
import re
import time

import requests

import demo_data
import settings

EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_ITEM_URL = "https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id"

_token_cache = {"token": None, "expires": 0}

log = logging.getLogger("dealscout")

# What the page shows. eBay's own error text never reaches the page, the
# history or the log; the log gets a status code or an exception name.
SIGNIN_UNREACHABLE = ("Couldn't reach eBay to sign in. Check your "
                      "connection and try again.")
SIGNIN_REFUSED = ("eBay turned down the sign-in. Check EBAY_CLIENT_ID and "
                  "EBAY_CLIENT_SECRET in your .env file.")
SIGNIN_BAD_ANSWER = ("eBay's sign-in answer didn't make sense. Try again "
                     "in a minute.")
SEARCH_FAILED = ("The eBay comp search failed, so there are no comps this "
                 "time. Try again in a minute.")
LISTING_FAILED = ("Couldn't load that eBay listing. Check the link, or "
                  "enter the details by hand.")


class EbayError(Exception):
    """Raised when eBay can't be reached or turns a request down. Its text
    is one of the plain messages above, safe to show on the page."""


def _failure(e: requests.RequestException) -> str:
    """A log-safe name for a failed request: never its address or body."""
    return "Timeout" if isinstance(e, requests.Timeout) else type(e).__name__


def _get_token() -> str:
    """Log in to eBay using your app keys (client-credentials flow).
    Tokens last ~2 hours; we reuse them until they expire."""
    if _token_cache["token"] and time.time() < _token_cache["expires"] - 60:
        return _token_cache["token"]

    client_id = os.environ.get("EBAY_CLIENT_ID", "")
    client_secret = os.environ.get("EBAY_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise EbayError("eBay keys missing. Add EBAY_CLIENT_ID and "
                        "EBAY_CLIENT_SECRET to your .env file, or set "
                        "DEALSCOUT_DEMO_MODE=on in .env to use demo data.")

    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        r = requests.post(
            EBAY_TOKEN_URL,
            headers={"Authorization": f"Basic {creds}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials",
                  "scope": "https://api.ebay.com/oauth/api_scope"},
            timeout=20)
    except requests.RequestException as e:
        log.warning("eBay sign-in failed: %s", _failure(e))
        raise EbayError(SIGNIN_UNREACHABLE) from None
    if r.status_code != 200:
        log.warning("eBay sign-in failed: HTTP %s", r.status_code)
        if r.status_code in (400, 401, 403):
            raise EbayError(SIGNIN_REFUSED)
        raise EbayError(SIGNIN_BAD_ANSWER)

    data = r.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires"] = time.time() + int(data.get("expires_in", 7200))
    return _token_cache["token"]


def search_comps(query: str, asking_price: float) -> list[dict]:
    """Search eBay for comparable ACTIVE listings.
    Returns a list of {title, price, url}. The asking price is only used
    by demo mode, to price the made-up comps around it."""
    if settings.DEMO_MODE:
        return _demo_comps(query, asking_price)

    token = _get_token()
    try:
        r = requests.get(
            EBAY_SEARCH_URL,
            headers={"Authorization": f"Bearer {token}",
                     "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            params={"q": query, "limit": settings.COMPS_TO_FETCH,
                    "filter": "buyingOptions:{FIXED_PRICE}"},
            timeout=20)
    except requests.RequestException as e:
        log.warning("eBay comp search failed: %s", _failure(e))
        raise EbayError(SEARCH_FAILED) from None
    if r.status_code != 200:
        log.warning("eBay comp search failed: HTTP %s", r.status_code)
        if r.status_code == 401:
            _token_cache.update(token=None, expires=0)
        raise EbayError(SEARCH_FAILED)

    comps = []
    for item in r.json().get("itemSummaries", []):
        price = item.get("price", {}).get("value")
        if price:
            comps.append({
                "title": item.get("title", ""),
                "price": float(price),
                "url": item.get("itemWebUrl", ""),
            })
    return comps


def extract_item_id(url: str) -> str | None:
    """Pull the item number out of an eBay listing URL."""
    m = re.search(r"/itm/(?:[^/]+/)?(\d{9,15})", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]item=(\d{9,15})", url)
    return m.group(1) if m else None


def fetch_listing_from_url(url: str) -> dict:
    """Given an eBay listing URL, pull its details via the official API.
    Returns {title, asking_price, description, image_urls}."""
    if settings.DEMO_MODE:
        # Any link gives the same sample listing; the form says so.
        return {**demo_data.SAMPLE_LISTING, "image_urls": []}

    item_id = extract_item_id(url)
    if not item_id:
        raise EbayError("That doesn't look like an eBay listing URL. "
                        "It should contain /itm/ followed by a number.")

    token = _get_token()
    try:
        r = requests.get(
            EBAY_ITEM_URL,
            headers={"Authorization": f"Bearer {token}",
                     "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            params={"legacy_item_id": item_id},
            timeout=20)
    except requests.RequestException as e:
        log.warning("eBay listing lookup failed: %s", _failure(e))
        raise EbayError(LISTING_FAILED) from None
    if r.status_code != 200:
        log.warning("eBay listing lookup failed: HTTP %s", r.status_code)
        if r.status_code == 401:
            _token_cache.update(token=None, expires=0)
        raise EbayError(LISTING_FAILED)

    data = r.json()
    images = []
    if data.get("image", {}).get("imageUrl"):
        images.append(data["image"]["imageUrl"])
    for extra in data.get("additionalImages", [])[:settings.MAX_PHOTOS - 1]:
        if extra.get("imageUrl"):
            images.append(extra["imageUrl"])

    return {
        "title": data.get("title", "(untitled eBay listing)"),
        "asking_price": float(data.get("price", {}).get("value", 0)),
        "description": (data.get("shortDescription")
                        or re.sub(r"<[^>]+>", " ",
                                  data.get("description", ""))[:2000]),
        "image_urls": images,
    }


# Demo comps center on the asking price times a ratio drawn from this
# range. The low end gives PASS and the high end BUY, with a NEGOTIATE
# band between them whose place shifts with the price and shipping.
DEMO_PRICE_RATIO = (0.8, 2.4)


def _demo_comps(query: str, asking_price: float) -> list[dict]:
    """Made-up comps for demo mode, priced around the asking price.
    Seeded from the query and price, so the same input always gives the
    same comps. Uses its own generator and leaves the global one alone."""
    rng = random.Random(f"{query}|{asking_price:.2f}")
    base = asking_price * rng.uniform(*DEMO_PRICE_RATIO)
    prices = [round(base * rng.uniform(0.75, 1.35), 2) for _ in range(14)]
    # Titles get their own generator so they never shift the prices.
    titles = demo_data.comp_titles(
        query, len(prices), random.Random(f"titles|{query}|{asking_price:.2f}"))
    return [{"title": t, "price": p, "url": "https://www.ebay.com"}
            for t, p in zip(titles, prices)]
