"""The fake Google and eBay server answers each path it promises, and
nothing but 127.0.0.1 gets through while it runs."""

import json
import socket
import unittest

import requests

from tests import NetworkBlocked
from tests.fake_server import (ALIAS, FAKE_GEMINI_KEY, RAW_MARKER,
                               fake_services)

GENERATE = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent")


def ask(model=ALIAS, text="Describe this listing"):
    return requests.post(GENERATE.format(model=model),
                         headers={"x-goog-api-key": FAKE_GEMINI_KEY},
                         json={"contents": [{"parts": [{"text": text}]}]},
                         timeout=5)


class FakeServerAnswers(unittest.TestCase):

    def test_alias_accepted(self):
        with fake_services() as server:
            answer = ask().json()
        self.assertEqual(answer["candidates"][0]["finishReason"], "STOP")
        report = json.loads(answer["candidates"][0]["content"]["parts"][0]["text"])
        self.assertEqual(report["category_guess"], "electronics")
        self.assertEqual(server.requests[0]["headers"]["x-goog-api-key"],
                         FAKE_GEMINI_KEY)

    def test_alias_refused(self):
        with fake_services() as server:
            server.open_models = {"gemini-3.8-flash"}
            refused = ask()
            accepted = ask("gemini-3.8-flash")
            listed = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                timeout=5).json()
        self.assertEqual(refused.status_code, 404)
        self.assertIn(RAW_MARKER, refused.text)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(listed["nextPageToken"], "page-2")

    def test_cut_off(self):
        with fake_services() as server:
            server.gemini = "cut_off"
            answer = ask().json()
        candidate = answer["candidates"][0]
        self.assertEqual(candidate["finishReason"], "MAX_TOKENS")
        with self.assertRaises(ValueError):
            json.loads(candidate["content"]["parts"][0]["text"])

    def test_blocked(self):
        with fake_services() as server:
            server.gemini = "blocked"
            answer = ask().json()
        self.assertEqual(answer, {"promptFeedback": {"blockReason": "SAFETY"}})

    def test_wrong_shape(self):
        with fake_services() as server:
            server.gemini = "top_list"
            whole = ask().json()
            server.gemini = "report_string"
            text = ask().json()["candidates"][0]["content"]["parts"][0]["text"]
        self.assertIsInstance(whole, list)
        self.assertIsInstance(json.loads(text), str)

    def test_timeout(self):
        with fake_services() as server:
            server.gemini = "timeout"
            with self.assertRaises(requests.Timeout):
                ask()

    def test_ebay_token_not_json(self):
        with fake_services() as server:
            server.ebay = {"token": "not_json"}
            answer = requests.post("https://api.ebay.com/identity/v1/oauth2/token",
                                   timeout=5)
        with self.assertRaises(ValueError):
            answer.json()


class OnlyLoopbackGetsThrough(unittest.TestCase):

    def test_other_hosts_stay_blocked_while_the_fake_runs(self):
        with fake_services():
            with self.assertRaises(NetworkBlocked):
                requests.get("https://example.com", timeout=1)
            with self.assertRaises(NetworkBlocked):
                socket.create_connection(("example.com", 443))
            with self.assertRaises(NetworkBlocked):
                socket.getaddrinfo("localhost", 80)


if __name__ == "__main__":
    unittest.main()
