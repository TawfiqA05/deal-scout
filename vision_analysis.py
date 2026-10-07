"""
Deal Scout photo & description analysis — powered by Google Gemini (free).

Sends the listing photos and text to Gemini and gets back:
  - a condition assessment
  - authenticity / scam red flags
  - what's missing that you should ask the seller
  - a category guess (used to pick the right eBay fee)

Uses the free Gemini API — no credit card, no expiration (Google's free
tier as of 2026: ~1,500 requests/day on the Flash model, which is far
more than a reseller doing manual analyses would ever hit). The only
tradeoff vs. a paid model: occasionally slightly less sharp on subtle
condition judgment calls, but plenty good for this.

If DEMO_MODE is on, returns a realistic fake report instead.
"""

import base64
import json
import logging
import os
from pathlib import Path

import demo_data
import gemini
import settings

log = logging.getLogger("dealscout")

# What the page shows, by the kind of failure gemini.py reports.
MESSAGES = {
    "timeout": "The photo check took too long to answer, so this result "
               "skips it. Try again in a minute.",
    "network": "Couldn't reach Google for the photo check, so this result "
               "skips it. Check your connection and try again.",
    "refused": "Google turned down the photo check request, so this result "
               "skips it. If it keeps happening, check GEMINI_API_KEY in "
               "your .env file.",
    "limit": "Google's limit for your key was reached, so this result skips "
             "the photo check. Try again later.",
    "server": "Google had a problem on its side, so this result skips the "
              "photo check. Try again in a minute.",
    "blocked": "Google blocked the photo check for this listing, so this "
               "result skips it.",
    "shape": "The photo check answer came back in a form the tool can't "
             "read, so this result skips it. Try again.",
}

_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp",
                ".gif": "image/gif"}

PROMPT = """You are helping a reseller evaluate a marketplace listing they might buy to flip.

Listing title: {title}
Asking price: ${price}
Description: {description}

Look at the photos (if any) and the text. Respond ONLY with JSON, no other text, no markdown code fences, in exactly this shape:
{{
  "condition": "one short sentence on apparent condition",
  "condition_grade": "one of: Like New / Good / Fair / Poor / Unknown",
  "red_flags": ["short bullet", "..."],
  "missing_info": ["what to ask the seller before buying", "..."],
  "category_guess": "short category like: tools, electronics, sneakers, video games, collectibles, clothing, etc.",
  "resale_title_suggestion": "a strong eBay search/listing title for this exact item, including brand and model if visible"
}}
Keep red_flags and missing_info honest and specific. Empty lists are fine if there's nothing to flag."""


def _encode_photo(path: Path) -> dict | None:
    """Gemini wants images as inlineData, not a URL or file upload."""
    media = _MEDIA_TYPES.get(path.suffix.lower())
    if not media:
        return None
    try:
        data = base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return None
    return {"inlineData": {"mimeType": media, "data": data}}


def analyze(title: str, price: float, description: str,
            photo_paths: list[Path]) -> dict:
    """Returns the vision report dict. Never crashes the app — on any
    failure it returns a report explaining what went wrong."""
    if settings.DEMO_MODE:
        return demo_data.vision_report(title)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return _error_report("Gemini API key missing. Add GEMINI_API_KEY "
                             "to your .env file (free at "
                             "aistudio.google.com), or set "
                             "DEALSCOUT_DEMO_MODE=on in .env to use demo "
                             "data.")

    parts = []
    for p in photo_paths[:settings.MAX_PHOTOS]:
        block = _encode_photo(Path(p))
        if block:
            parts.append(block)
    parts.append({"text": PROMPT.format(
        title=title, price=price, description=(description or "(none)")[:3000])})

    try:
        text = gemini.generate(api_key, parts, max_tokens=1000, timeout=90)
    except gemini.GeminiError as e:
        log.warning("Photo check failed: %s", e.detail)
        return _error_report(MESSAGES[e.kind])
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        report = json.loads(text)
    except ValueError:
        log.warning("Photo check failed: unreadable answer")
        return _error_report(MESSAGES["shape"])
    # Make sure every field the results page expects is present:
    report.setdefault("condition", "Unknown")
    report.setdefault("condition_grade", "Unknown")
    report.setdefault("red_flags", [])
    report.setdefault("missing_info", [])
    report.setdefault("category_guess", None)
    report.setdefault("resale_title_suggestion", title)
    return report


def _error_report(msg: str) -> dict:
    return {"condition": None, "condition_grade": "Unknown",
            "red_flags": [], "missing_info": [],
            "category_guess": None, "resale_title_suggestion": None,
            "error": msg}
