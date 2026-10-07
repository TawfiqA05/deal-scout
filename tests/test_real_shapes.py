"""Answers in the wrong shape from Gemini or eBay give a plain message or a
sensible result, never a 500."""

import json
import re
import sqlite3
import unittest

from tests import real_messages as msg
from tests.fake_server import ALIAS, COMP_PRICES, GOOD_REPORT
from tests.fake_server import _reset_caches as reset_caches
from tests.helpers import RealModeTest

LISTING_URL = "https://www.ebay.com/itm/Bose-SoundLink-Flex/123456789012"


def bullets(page):
    return re.findall(r"<li>(.*?)</li>", page)


class GeminiShapes(RealModeTest):

    def setUp(self):
        super().setUp()
        # Every model answers, so each test reaches the shape it sends.
        self.server.open_models = {ALIAS, "gemini-2.5-flash"}

    def test_report_that_is_not_an_object(self):
        for mode in ("top_list", "report_list", "report_string"):
            with self.subTest(mode=mode):
                self.server.gemini = mode
                status, page = self.analyze()
                self.assertEqual(status, 200)
                self.assertIn(msg.PHOTO_SHAPE, page)

    def test_category_given_as_a_list(self):
        self.server.gemini = "category_list"
        status, page = self.analyze()
        self.assertEqual(status, 200)
        row = self.saved_rows()[0]
        self.assertEqual(row["category_guess"], "electronics")
        self.assertEqual(row["fee_percent"], 13.25)

    def test_red_flags_given_as_one_string(self):
        self.server.gemini = "flags_string"
        status, page = self.analyze()
        self.assertEqual(status, 200)
        flags = bullets(page.split("Red flags", 1)[1].split("</ul>", 1)[0])
        self.assertEqual(flags, ["No photo of it powered on"])
        self.assertEqual(self.saved_rows()[0]["vision_report"]["red_flags"],
                         ["No photo of it powered on"])

    def test_fields_of_the_wrong_type_fall_back(self):
        import vision_analysis
        report = vision_analysis.clean_report({
            "condition": 7, "condition_grade": None, "red_flags": {"a": 1},
            "missing_info": ["Ask about the cable", 3, ""],
            "category_guess": [], "resale_title_suggestion": ""},
            "Bose SoundLink Flex speaker")
        self.assertEqual(report, {
            "condition": "Unknown", "condition_grade": "Unknown",
            "red_flags": [], "missing_info": ["Ask about the cable"],
            "category_guess": None,
            "resale_title_suggestion": "Bose SoundLink Flex speaker"})


class EbayShapes(RealModeTest):

    def setUp(self):
        super().setUp()
        self.server.open_models = {ALIAS, "gemini-2.5-flash"}

    def test_token_answer_that_is_not_usable(self):
        for mode in ("not_json", "no_token", "top_list"):
            with self.subTest(mode=mode):
                reset_caches()
                self.server.ebay = {"token": mode}
                status, page = self.analyze()
                self.assertEqual(status, 200)
                self.assertIn(msg.EBAY_SIGNIN_BAD_ANSWER, page)

    def test_search_answer_that_is_not_usable(self):
        for mode in ("not_json", "top_list"):
            with self.subTest(mode=mode):
                self.server.ebay = {"search": mode}
                status, page = self.analyze()
                self.assertEqual(status, 200)
                self.assertIn(msg.EBAY_SEARCH_FAILED, page)

    def test_search_skips_items_without_a_usable_price(self):
        self.server.ebay = {"search": "bad_prices"}
        status, page = self.analyze()
        self.assertEqual(status, 200)
        self.assertEqual(self.saved_rows()[0]["comps_count"], len(COMP_PRICES))

    def test_listing_answer_that_is_not_usable(self):
        for mode in ("not_json", "top_list"):
            with self.subTest(mode=mode):
                self.server.ebay = {"item": mode}
                status, page = self.analyze(ebay_url=LISTING_URL)
                self.assertEqual(status, 200)
                self.assertIn(msg.EBAY_LISTING_FAILED, page)

    def test_listing_with_an_odd_price(self):
        self.server.ebay = {"item": "bad_prices"}
        status, page = self.analyze(ebay_url=LISTING_URL)
        self.assertEqual(status, 200)
        self.assertIn("didn't return a usable price", page)


class OldRowsInHistory(RealModeTest):

    def test_saved_string_of_red_flags_shows_as_one_bullet(self):
        report = dict(GOOD_REPORT, red_flags="Seller won't show the serial",
                      missing_info="Ask for the receipt")
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO listings (analyzed_at, title, asking_price, verdict,"
            " vision_report) VALUES (?,?,?,?,?)",
            ("2026-09-20T09:30:00", "Bose SoundLink Flex speaker", 35.0,
             "PASS", json.dumps(report)))
        conn.commit()
        conn.close()
        page = self.history_page()
        self.assertIn("<li>Seller won't show the serial</li>", page)
        self.assertIn("<li>Ask for the receipt</li>", page)
        self.assertNotIn("<li>S</li>", page)


if __name__ == "__main__":
    unittest.main()
