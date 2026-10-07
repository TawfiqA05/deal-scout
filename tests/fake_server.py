"""A local stand-in for Google's Gemini API and eBay's APIs.

fake_services() starts a small HTTP server on 127.0.0.1 and reroutes any
request for generativelanguage.googleapis.com, api.ebay.com or
i.ebayimg.com to it, so the app's own code runs unchanged and nothing
leaves the machine. Each test sets what the server answers through
server.gemini, server.ebay and server.open_models, and reads what the app
sent from server.requests.

Gemini answers (server.gemini):
  "ok"            a photo report in the right shape, or a draft message
  "cut_off"       half a report with finishReason MAX_TOKENS
  "blocked"       no candidates and promptFeedback.blockReason SAFETY
  "blocked_finish" a candidate stopped with finishReason SAFETY
  "top_list"      the whole answer is a JSON list
  "report_list"   the report text is a JSON list
  "report_string" the report text is a JSON string
  "category_list" category_guess is a list
  "flags_string"  red_flags is one string
  "timeout"       answers after the client has given up
  "http_400", "http_403", "http_429", "http_500"  an error answer
A host in server.unreachable refuses the connection.
A model not in server.open_models is refused with a 404, the way Google
refuses a model an account can't use. The alias is open by default.

eBay answers (server.ebay, one key per call: token, search, item):
  "ok", "not_json", "no_token", "http_401", "http_500", "timeout",
  "top_list", "bad_prices"

Every error answer echoes the address it was asked for, key and all, plus
RAW_MARKER, so a test can tell if raw error text ever reaches the page.
"""

import base64
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlsplit, urlunsplit

import requests

FAKE_GEMINI_KEY = "fake-gemini-key-for-tests-7f3a91"
FAKE_EBAY_ID = "fake-ebay-client-id-55c2"
FAKE_EBAY_SECRET = "fake-ebay-client-secret-0b9e44"
FAKE_EBAY_TOKEN = "fake-ebay-access-token-d41f"
RAW_MARKER = "RAW-UPSTREAM-ERROR-TEXT"
ALIAS = "gemini-flash-latest"

FAKE_HOSTS = {"generativelanguage.googleapis.com", "api.ebay.com",
              "i.ebayimg.com"}
CLIENT_TIMEOUT = 0.5        # the most any rerouted request waits
SLOW_ANSWER_SECONDS = 1.5   # how long a "timeout" answer takes

# A 1x1 PNG, served as the eBay listing photo.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
    "DwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

GOOD_REPORT = {
    "condition": "Light scuffs on the base. The grille has no dents.",
    "condition_grade": "Good",
    "red_flags": ["No photo of it powered on"],
    "missing_info": ["Ask if the charging cable comes with it"],
    "category_guess": "electronics",
    "resale_title_suggestion": "Bose SoundLink Flex Bluetooth speaker black",
}
DRAFT_TEXT = "Hi! Is the speaker still around? Would you take $40 for it?"

LISTED_MODELS = [
    # page 1
    [{"name": "models/gemini-2.5-flash",
      "supportedGenerationMethods": ["generateContent"]},
     {"name": "models/gemini-3.8-flash-lite",
      "supportedGenerationMethods": ["generateContent"]},
     {"name": "models/gemini-embedding-001",
      "supportedGenerationMethods": ["embedContent"]}],
    # page 2
    [{"name": "models/gemini-3.7-flash",
      "supportedGenerationMethods": ["generateContent"]},
     {"name": "models/gemini-3.8-flash",
      "supportedGenerationMethods": ["generateContent", "countTokens"]},
     {"name": "models/gemini-3.8-flash-tts",
      "supportedGenerationMethods": ["generateContent"]},
     {"name": "models/gemini-9.9-flash",
      "supportedGenerationMethods": ["embedContent"]}],
]

COMP_PRICES = [42.0, 45.5, 48.0, 50.0, 51.0, 52.5, 55.0, 56.0, 58.0, 60.0,
               62.0, 65.0]


def _report_text(mode):
    report = dict(GOOD_REPORT)
    if mode == "report_list":
        return json.dumps(["Good", "electronics"])
    if mode == "report_string":
        return json.dumps("The speaker looks fine.")
    if mode == "category_list":
        report["category_guess"] = ["electronics", "speakers"]
    if mode == "flags_string":
        report["red_flags"] = "No photo of it powered on"
    if mode == "cut_off":
        return json.dumps(report)[:40]
    return json.dumps(report)


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeUpstream/1"

    def log_message(self, *args):
        pass

    # Requests arrive as /<original host>/<original path>?<query>.
    def _split(self):
        parts = urlsplit(self.path)
        host, _, path = parts.path.lstrip("/").partition("/")
        return host, "/" + path, parts.query

    def _record(self, body):
        host, path, query = self._split()
        try:
            parsed = json.loads(body) if body else None
        except ValueError:
            parsed = body.decode(errors="replace")
        entry = {"method": self.command, "host": host, "path": path,
                 "query": parse_qs(query), "raw_query": query,
                 "headers": {k.lower(): v for k, v in self.headers.items()},
                 "body": parsed}
        self.server.requests.append(entry)
        return entry

    def _send(self, status, payload, content_type="application/json"):
        data = payload if isinstance(payload, bytes) else (
            payload if isinstance(payload, str) else json.dumps(payload)
        ).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass  # the client gave up first, which is the point of "timeout"

    def _error(self, status, entry):
        # Real error answers can repeat what was asked; this one repeats
        # everything, so a leak would show.
        self._send(status, {"error": {
            "code": status, "status": "ERROR",
            "message": f"{RAW_MARKER} for {entry['host']}{entry['path']}"
                       f"?{entry['raw_query']}"}})

    def do_GET(self):
        entry = self._record(b"")
        if entry["host"] == "i.ebayimg.com":
            return self._send(200, PNG, "image/png")
        if entry["host"] == "generativelanguage.googleapis.com":
            return self._list_models(entry)
        if entry["path"].endswith("/item_summary/search"):
            return self._ebay("search", entry)
        if entry["path"].endswith("/item/get_item_by_legacy_id"):
            return self._ebay("item", entry)
        self._send(404, {"error": "no such fake path"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        entry = self._record(self.rfile.read(length))
        if entry["host"] == "api.ebay.com":
            return self._ebay("token", entry)
        if entry["path"].endswith(":generateContent"):
            return self._generate(entry)
        self._send(404, {"error": "no such fake path"})

    def _list_models(self, entry):
        self.server.list_calls += 1
        page = 1 if entry["query"].get("pageToken") == ["page-2"] else 0
        payload = {"models": LISTED_MODELS[page]}
        if page == 0:
            payload["nextPageToken"] = "page-2"
        if not self.server.list_has_flash:
            payload = {"models": [m for m in LISTED_MODELS[0]
                                  if "embedding" in m["name"]]}
        self._send(200, payload)

    def _generate(self, entry):
        model = entry["path"].rsplit("/", 1)[-1].split(":")[0]
        if model not in self.server.open_models:
            return self._send(404, {"error": {
                "code": 404, "status": "NOT_FOUND",
                "message": f"{RAW_MARKER} models/{model} is not found "
                           f"?{entry['raw_query']}"}})
        mode = self.server.gemini
        if mode == "timeout":
            time.sleep(SLOW_ANSWER_SECONDS)
            return self._send(200, {"candidates": []})
        if mode.startswith("http_"):
            return self._error(int(mode[5:]), entry)
        if mode == "top_list":
            return self._send(200, [{"candidates": []}])
        if mode == "blocked":
            return self._send(200, {"promptFeedback": {"blockReason": "SAFETY"}})
        if mode == "blocked_finish":
            return self._send(200, {"candidates": [{"finishReason": "SAFETY"}]})
        prompt = json.dumps(entry["body"])
        is_draft = "negotiation message" in prompt
        text = DRAFT_TEXT if is_draft else _report_text(mode)
        if is_draft and mode == "cut_off":
            text = DRAFT_TEXT[:20]
        finish = "MAX_TOKENS" if mode == "cut_off" else "STOP"
        self._send(200, {"candidates": [{
            "content": {"role": "model", "parts": [{"text": text}]},
            "finishReason": finish}],
            "modelVersion": model})

    def _ebay(self, call, entry):
        mode = self.server.ebay.get(call, "ok")
        if mode == "timeout":
            time.sleep(SLOW_ANSWER_SECONDS)
            return self._send(200, {})
        if mode.startswith("http_"):
            return self._error(int(mode[5:]), entry)
        if mode == "not_json":
            return self._send(200, f"<html>{RAW_MARKER} maintenance</html>",
                              "text/html")
        if mode == "top_list":
            return self._send(200, [])
        if call == "token":
            if mode == "no_token":
                return self._send(200, {"token_type": "Application Access Token"})
            return self._send(200, {"access_token": FAKE_EBAY_TOKEN,
                                    "expires_in": 7200,
                                    "token_type": "Application Access Token"})
        if call == "search":
            items = [{"title": f"Bose SoundLink Flex speaker, lot {i + 1}",
                      "price": {"value": f"{p:.2f}", "currency": "USD"},
                      "itemWebUrl": f"https://www.ebay.com/itm/{3000 + i}"}
                     for i, p in enumerate(COMP_PRICES)]
            if mode == "bad_prices":
                items += [{"title": "No price"}, "not an item",
                          {"title": "Odd price", "price": {"value": "call me"}},
                          {"title": "Price list", "price": [1, 2]}]
            return self._send(200, {"itemSummaries": items,
                                    "total": len(items)})
        # call == "item"
        if mode == "bad_prices":
            return self._send(200, {"title": "Bose SoundLink Flex speaker",
                                    "price": {"value": "call me"}})
        return self._send(200, {
            "title": "Bose SoundLink Flex Bluetooth speaker, black",
            "price": {"value": "35.00", "currency": "USD"},
            "shortDescription": "Works fine. Light scuffs on the base.",
            "image": {"imageUrl": "https://i.ebayimg.com/images/g/abc/s-l1600.png"},
            "additionalImages": [],
        })


class FakeServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.requests = []
        self.gemini = "ok"
        self.ebay = {}
        self.open_models = {ALIAS}
        self.list_has_flash = True
        self.list_calls = 0
        self.unreachable = set()

    def handle_error(self, request, client_address):
        pass

    def calls_to(self, host):
        return [r for r in self.requests if r["host"] == host]


def _reset_caches():
    import sys
    ebay_api = sys.modules.get("ebay_api")
    if ebay_api is not None:
        ebay_api._token_cache.update(token=None, expires=0)
    gemini = sys.modules.get("gemini")
    if gemini is not None and hasattr(gemini, "forget_chosen_model"):
        gemini.forget_chosen_model()


@contextmanager
def fake_services(demo_mode=False):
    """Run the app in real mode with fake keys against the fake server."""
    import settings

    server = FakeServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_send = requests.adapters.HTTPAdapter.send

    def rerouted_send(adapter, request, **kwargs):
        parts = urlsplit(request.url)
        if parts.hostname in FAKE_HOSTS:
            # An unreachable host goes to a port nobody listens on.
            port = 1 if parts.hostname in server.unreachable else server.server_port
            request.url = urlunsplit((
                "http", f"127.0.0.1:{port}",
                f"/{parts.hostname}{parts.path}", parts.query, ""))
            timeout = kwargs.get("timeout")
            if not isinstance(timeout, (int, float)) or timeout > CLIENT_TIMEOUT:
                kwargs["timeout"] = CLIENT_TIMEOUT
        return original_send(adapter, request, **kwargs)

    _reset_caches()
    try:
        with mock.patch.object(requests.adapters.HTTPAdapter, "send",
                               rerouted_send), \
                mock.patch.object(settings, "DEMO_MODE", demo_mode), \
                mock.patch.dict("os.environ", {
                    "GEMINI_API_KEY": FAKE_GEMINI_KEY,
                    "EBAY_CLIENT_ID": FAKE_EBAY_ID,
                    "EBAY_CLIENT_SECRET": FAKE_EBAY_SECRET}):
            yield server
    finally:
        _reset_caches()
        server.shutdown()
        server.server_close()
