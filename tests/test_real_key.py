"""The Gemini key travels only in a header, and no raw error text from
Google or eBay reaches the page, the database or the log."""

import base64
import unittest

import negotiator
from tests import real_messages as msg
from tests.fake_server import (ALIAS, DRAFT_TEXT, FAKE_EBAY_ID,
                               FAKE_EBAY_SECRET, FAKE_EBAY_TOKEN,
                               FAKE_GEMINI_KEY, RAW_MARKER)
from tests.fake_server import _reset_caches as reset_caches
from tests.helpers import RealModeTest

LISTING_URL = "https://www.ebay.com/itm/Bose-SoundLink-Flex/123456789012"
BASIC = base64.b64encode(f"{FAKE_EBAY_ID}:{FAKE_EBAY_SECRET}".encode()).decode()
SECRETS = [FAKE_GEMINI_KEY, FAKE_EBAY_SECRET, BASIC, FAKE_EBAY_TOKEN]
# Raw error text from requests or from the answer body.
RAW_TEXT = [RAW_MARKER, "Client Error", "Server Error", "for url",
            "HTTPConnectionPool", "HTTPSConnectionPool", "Read timed out",
            "Max retries", "Traceback"]

# (what Google does, what eBay does, eBay link or not, the message expected)
FAILURES = [
    ("http_400", {}, False, msg.PHOTO_REFUSED),
    ("http_403", {}, False, msg.PHOTO_REFUSED),
    ("http_429", {}, False, msg.PHOTO_LIMIT),
    ("http_500", {}, False, msg.PHOTO_SERVER),
    ("timeout", {}, False, msg.PHOTO_TIMEOUT),
    ("blocked", {}, False, msg.PHOTO_BLOCKED),
    ("ok", {"token": "http_401"}, False, msg.EBAY_SIGNIN_REFUSED),
    ("ok", {"token": "timeout"}, False, msg.EBAY_SIGNIN_UNREACHABLE),
    ("ok", {"search": "http_500"}, False, msg.EBAY_SEARCH_FAILED),
    ("ok", {"item": "http_500"}, True, msg.EBAY_LISTING_FAILED),
    ("http_400", {"search": "http_500"}, False, msg.EBAY_SEARCH_FAILED),
]


class KeyTest(RealModeTest):

    def setUp(self):
        super().setUp()
        # The model change is tested on its own; here every model answers,
        # so each test reaches the failure it forces.
        self.server.open_models = {ALIAS, "gemini-2.5-flash"}


class KeyStaysInTheHeader(KeyTest):

    def test_photo_check_sends_the_key_in_a_header(self):
        status, page = self.analyze()
        self.assertEqual(status, 200)
        calls = self.gemini_calls()
        self.assertEqual(len(calls), 1)
        for call in calls:
            self.assertEqual(call["headers"].get("x-goog-api-key"), FAKE_GEMINI_KEY)
            self.assertNotIn("key", call["query"])
            self.assertNotIn(FAKE_GEMINI_KEY, call["raw_query"] + call["path"])

    def test_offer_draft_sends_the_key_in_a_header(self):
        draft = negotiator.draft_message("Bose SoundLink Flex speaker", 60.0,
                                         40.0, "Light scuffs", [])
        self.assertEqual(draft, DRAFT_TEXT)
        call = self.gemini_calls()[0]
        self.assertEqual(call["headers"].get("x-goog-api-key"), FAKE_GEMINI_KEY)
        self.assertNotIn(FAKE_GEMINI_KEY, call["raw_query"] + call["path"])


class FailuresLeaveNoTrace(KeyTest):

    def run_failure(self, gemini, ebay, use_link):
        reset_caches()
        self.server.gemini = gemini
        self.server.ebay = ebay
        form = {"ebay_url": LISTING_URL} if use_link else {}
        status, page = self.analyze(**form)
        return status, page

    def test_key_and_raw_text_appear_nowhere(self):
        for gemini, ebay, use_link, expected in FAILURES:
            with self.subTest(gemini=gemini, ebay=ebay):
                status, page = self.run_failure(gemini, ebay, use_link)
                places = {"page": page, "history": self.history_page(),
                          "database": self.db_bytes().decode(errors="replace"),
                          "log": self.log_text()}
                for where, text in places.items():
                    for secret in SECRETS:
                        self.assertNotIn(secret, text, where)
                    for raw in RAW_TEXT:
                        self.assertNotIn(raw, text, where)
                    self.assertNotIn("key=", text, where)
                for where in ("page", "history", "database"):
                    self.assertNotIn("googleapis", places[where], where)
                    self.assertNotIn("api.ebay.com", places[where], where)
                self.assertEqual(status, 200)
                self.assertIn(expected, page)

    def test_photo_message_is_saved_with_the_row(self):
        self.server.gemini = "http_403"
        self.analyze()
        row = self.saved_rows()[0]
        self.assertEqual(row["vision_report"]["error"], msg.PHOTO_REFUSED)

    def test_unreachable_google_and_ebay(self):
        self.server.unreachable = {"generativelanguage.googleapis.com"}
        status, page = self.analyze()
        self.assertEqual(status, 200)
        self.assertIn(msg.PHOTO_NETWORK, page)
        reset_caches()
        self.server.unreachable = {"api.ebay.com"}
        status, page = self.analyze(title="Bose SoundLink Flex speaker, blue")
        self.assertIn(msg.EBAY_SIGNIN_UNREACHABLE, page)
        for raw in RAW_TEXT:
            self.assertNotIn(raw, page)
            self.assertNotIn(raw, self.log_text())

    def test_log_names_the_failure_without_details(self):
        self.server.gemini = "http_403"
        self.server.ebay = {"token": "http_401"}
        self.analyze()
        log = self.log_text()
        self.assertIn("Photo check failed: HTTP 403 from Google", log)
        self.assertIn("eBay sign-in failed: HTTP 401", log)


if __name__ == "__main__":
    unittest.main()
