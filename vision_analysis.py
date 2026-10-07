"""
Deal Scout photo and description check, using Google Gemini.

Sends the listing photos and text to Gemini and gets back:
  - a condition assessment
  - authenticity / scam red flags
  - what's missing that you should ask the seller
  - a category guess (used to pick the right eBay fee)

The answer is JSON that follows REPORT_SCHEMA. If DEMO_MODE is on, this
returns a made-up report instead and makes no network call.
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
    "cut_off": "The photo check answer was cut off, so this result skips "
               "it. Try again.",
    "shape": "The photo check answer came back in a form the tool can't "
             "read, so this result skips it. Try again.",
    "no_model": "No Gemini Flash model is open to your key right now, so "
                "this result skips the photo check.",
}

# Room for the report, with thinking at its lowest. Thinking counts
# against this limit too.
MAX_OUTPUT_TOKENS = 8192

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "condition": {"type": "string"},
        "condition_grade": {"type": "string", "enum": [
            "Like New", "Good", "Fair", "Poor", "Unknown"]},
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "missing_info": {"type": "array", "items": {"type": "string"}},
        "category_guess": {"type": "string"},
        "resale_title_suggestion": {"type": "string"},
    },
    "required": ["condition", "condition_grade", "red_flags", "missing_info",
                 "category_guess", "resale_title_suggestion"],
}

_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp",
                ".gif": "image/gif"}

PROMPT = """You are helping a reseller evaluate a marketplace listing they might buy to flip.

Listing title: {title}
Asking price: ${price}
Description: {description}

Look at the photos (if any) and the text. Answer in JSON with these fields:
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
        text = gemini.generate(api_key, parts, max_tokens=MAX_OUTPUT_TOKENS,
                               timeout=90, json_schema=REPORT_SCHEMA)
    except gemini.GeminiError as e:
        log.warning("Photo check failed: %s", e.detail)
        return _error_report(MESSAGES[e.kind])
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
