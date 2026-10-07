"""
Calls to Google Gemini, shared by the photo check and the offer draft.

The key goes in the x-goog-api-key header, never in the address. A failure
comes back as a GeminiError: its kind picks the plain message the caller
shows, and its detail is for the log. The detail only ever holds a status
code, an exception name or one of Google's reason codes, never the address
or the text of an answer.

settings.GEMINI_MODEL is Google's latest-Flash alias. If Google refuses it
(a 404), the newest plain Flash model from the list-models call is used
instead and kept until the process ends.
"""

import logging
import re

import requests

import settings

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
LIST_TIMEOUT = 20
LIST_MAX_PAGES = 10

log = logging.getLogger("dealscout")

# Set once the alias is refused and a model is picked from the list.
_chosen_model = {"name": None}

# Finish reasons that mean Google stopped the answer on purpose.
_BLOCKED_REASONS = {"SAFETY", "RECITATION", "LANGUAGE", "BLOCKLIST",
                    "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY",
                    "IMAGE_PROHIBITED_CONTENT", "IMAGE_RECITATION",
                    "PUP_LIMITED_DISABLED", "ESCALATION"}

_PLAIN_FLASH = re.compile(r"gemini-(\d+)(?:\.(\d+))?-flash")


class GeminiError(Exception):
    """kind is one of: timeout, network, refused, limit, server, cut_off,
    blocked, shape, no_model."""

    def __init__(self, kind: str, detail: str, status: int | None = None):
        super().__init__(kind)
        self.kind = kind
        self.detail = detail
        self.status = status


def forget_chosen_model() -> None:
    """Go back to trying the alias first. Tests use this."""
    _chosen_model["name"] = None


def thinking_config(model: str) -> dict:
    """The lowest thinking setting each model takes, per Google's thinking
    guide: 3.7 Flash and later take "low" at the least ("minimal" is an
    error there), earlier 3.x Flash takes "minimal", and 2.x turns thinking
    off with a budget of 0. The alias names no version and points at the
    newest Flash, so it gets "low"."""
    match = re.search(r"gemini-(\d+)(?:\.(\d+))?", model)
    if not match:
        return {"thinkingLevel": "low"}
    version = (int(match.group(1)), int(match.group(2) or 0))
    if version < (3, 0):
        return {"thinkingBudget": 0}
    if version >= (3, 7):
        return {"thinkingLevel": "low"}
    return {"thinkingLevel": "minimal"}


def generate(api_key: str, parts: list[dict], max_tokens: int,
             timeout: float, json_schema: dict | None = None) -> str:
    """Send one request and return the answer's text. With json_schema the
    answer is JSON that follows it; without, it's plain text."""
    model = _chosen_model["name"] or settings.GEMINI_MODEL
    try:
        data = _post(model, api_key, parts, max_tokens, timeout, json_schema)
    except GeminiError as e:
        if e.status != 404 or model != settings.GEMINI_MODEL:
            raise
        picked = _pick_from_model_list(api_key)
        log.warning("%s was refused, using %s from the model list",
                    settings.GEMINI_MODEL, picked)
        _chosen_model["name"] = picked
        data = _post(picked, api_key, parts, max_tokens, timeout, json_schema)
    return _text_from(data)


def _post(model: str, api_key: str, parts: list[dict], max_tokens: int,
          timeout: float, json_schema: dict | None):
    config = {"maxOutputTokens": max_tokens,
              "thinkingConfig": thinking_config(model)}
    if json_schema is not None:
        config["responseMimeType"] = "application/json"
        config["responseJsonSchema"] = json_schema
    try:
        r = requests.post(
            f"{API_BASE}/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key,
                     "content-type": "application/json"},
            json={"contents": [{"parts": parts}], "generationConfig": config},
            timeout=timeout)
    except requests.Timeout:
        raise GeminiError("timeout", "Timeout") from None
    except requests.RequestException as e:
        raise GeminiError("network", type(e).__name__) from None
    if r.status_code != 200:
        raise GeminiError(_kind_for_status(r.status_code),
                          f"HTTP {r.status_code} from Google", r.status_code)
    try:
        return r.json()
    except ValueError:
        raise GeminiError("shape", "unreadable answer") from None


def _pick_from_model_list(api_key: str) -> str:
    """The newest plain Flash model (no Lite, TTS, image or preview) that
    takes generateContent, from Google's list-models call."""
    best, page_token = None, None
    for _ in range(LIST_MAX_PAGES):
        params = {"pageSize": 1000}
        if page_token:
            params["pageToken"] = page_token
        try:
            r = requests.get(f"{API_BASE}/models", params=params,
                             headers={"x-goog-api-key": api_key},
                             timeout=LIST_TIMEOUT)
            data = r.json() if r.status_code == 200 else None
        except requests.RequestException as e:
            raise GeminiError("no_model", f"model list: {type(e).__name__}") from None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise GeminiError("no_model", f"model list: HTTP {r.status_code}")
        models = data.get("models")
        for m in models if isinstance(models, list) else []:
            if not isinstance(m, dict) or not isinstance(m.get("name"), str):
                continue
            methods = m.get("supportedGenerationMethods")
            if not isinstance(methods, list) or "generateContent" not in methods:
                continue
            match = _PLAIN_FLASH.fullmatch(m["name"].removeprefix("models/"))
            if match:
                version = (int(match.group(1)), int(match.group(2) or 0))
                if best is None or version > best[0]:
                    best = (version, match.group(0))
        page_token = data.get("nextPageToken")
        if not isinstance(page_token, str) or not page_token:
            break
    if best is None:
        raise GeminiError("no_model", "no Flash model in the list")
    return best[1]


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
    finish = candidates[0].get("finishReason")
    if finish != "STOP":
        detail = f"finish reason {_code(finish)}"
        if finish == "MAX_TOKENS":
            raise GeminiError("cut_off", detail)
        if finish in _BLOCKED_REASONS:
            raise GeminiError("blocked", detail)
        raise GeminiError("shape", detail)
    content = candidates[0].get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise GeminiError("shape", "no parts")
    return "".join(p["text"] for p in parts
                   if isinstance(p, dict) and isinstance(p.get("text"), str)
                   and not p.get("thought"))
