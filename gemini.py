"""
Calls to Google Gemini, shared by the photo check and the offer draft.

The key goes in the x-goog-api-key header, never in the address. A failure
comes back as a GeminiError: its kind picks the plain message the caller
shows, and its detail is for the log. The detail only ever holds a status
code, an exception name or one of Google's reason codes, never the address
or the text of an answer.
"""

import re

import requests

import settings

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(Exception):
    """kind is one of: timeout, network, refused, limit, server, blocked,
    shape."""

    def __init__(self, kind: str, detail: str):
        super().__init__(kind)
        self.kind = kind
        self.detail = detail


def generate(api_key: str, parts: list[dict], max_tokens: int,
             timeout: float) -> str:
    """Send one request and return the answer's text."""
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"maxOutputTokens": max_tokens}}
    return _text_from(_post(settings.GEMINI_MODEL, api_key, body, timeout))


def _post(model: str, api_key: str, body: dict, timeout: float):
    try:
        r = requests.post(
            f"{API_BASE}/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key,
                     "content-type": "application/json"},
            json=body, timeout=timeout)
    except requests.Timeout:
        raise GeminiError("timeout", "Timeout") from None
    except requests.RequestException as e:
        raise GeminiError("network", type(e).__name__) from None
    if r.status_code != 200:
        raise GeminiError(_kind_for_status(r.status_code),
                          f"HTTP {r.status_code} from Google")
    try:
        return r.json()
    except ValueError:
        raise GeminiError("shape", "unreadable answer") from None


def _kind_for_status(status: int) -> str:
    if status in (400, 401, 403, 404):
        return "refused"
    if status == 429:
        return "limit"
    return "server"


def _code(value) -> str:
    """Google's reason codes are upper-case words. Anything else is
    reported as unknown, so the log never carries text from the answer."""
    if isinstance(value, str) and re.fullmatch(r"[A-Z_]{1,40}", value):
        return value
    return "unknown"


def _text_from(data) -> str:
    if not isinstance(data, dict):
        raise GeminiError("shape", "answer is not an object")
    candidates = data.get("candidates")
    if not candidates:
        feedback = data.get("promptFeedback")
        reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
        if reason:
            raise GeminiError("blocked", f"block reason {_code(reason)}")
        raise GeminiError("shape", "no candidates")
    if not isinstance(candidates, list) or not isinstance(candidates[0], dict):
        raise GeminiError("shape", "candidates in the wrong shape")
    content = candidates[0].get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise GeminiError("shape", "no parts")
    return "".join(p["text"] for p in parts
                   if isinstance(p, dict) and isinstance(p.get("text"), str)
                   and not p.get("thought"))
