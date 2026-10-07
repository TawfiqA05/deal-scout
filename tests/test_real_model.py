"""The model call: the latest-Flash alias with a list-models fallback,
JSON with a schema, the lowest thinking setting, room for the answer and
a finish-reason check. The draft call gets the same care in plain text."""

import unittest

import negotiator
import settings
from tests import REPO_DIR
from tests import real_messages as msg
from tests.fake_server import ALIAS, DRAFT_TEXT, GOOD_REPORT, RAW_MARKER
from tests.helpers import RealModeTest

REPORT_FIELDS = {"condition", "condition_grade", "red_flags", "missing_info",
                 "category_guess", "resale_title_suggestion"}


class PhotoCall(RealModeTest):

    def test_default_model_is_the_latest_flash_alias(self):
        self.assertEqual(settings.GEMINI_MODEL, ALIAS)

    def test_alias_accepted(self):
        status, page = self.analyze()
        self.assertEqual(status, 200)
        self.assertIn(GOOD_REPORT["condition"], page)
        calls = self.gemini_calls()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["path"].endswith(f"/models/{ALIAS}:generateContent"))
        self.assertEqual(self.server.list_calls, 0)

    def test_request_asks_for_json_with_a_schema(self):
        self.analyze()
        config = self.gemini_calls()[0]["body"]["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        schema = config["responseJsonSchema"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(set(schema["properties"]), REPORT_FIELDS)
        self.assertEqual(set(schema["required"]), REPORT_FIELDS)
        self.assertEqual(schema["properties"]["red_flags"]["type"], "array")
        self.assertNotIn("responseSchema", config)

    def test_thinking_is_low_and_there_is_room_for_the_answer(self):
        self.analyze()
        config = self.gemini_calls()[0]["body"]["generationConfig"]
        self.assertEqual(config["thinkingConfig"], {"thinkingLevel": "low"})
        self.assertGreaterEqual(config["maxOutputTokens"], 8192)

    def test_alias_refused_falls_back_to_the_model_list_once(self):
        self.server.open_models = {"gemini-3.8-flash"}
        status, page = self.analyze()
        self.assertEqual(status, 200)
        self.assertIn(GOOD_REPORT["condition"], page)
        self.assertEqual(self.server.list_calls, 2)   # two pages
        calls = self.gemini_calls()
        self.assertEqual([c["path"].rsplit("/", 1)[-1] for c in calls],
                         [f"{ALIAS}:generateContent",
                          "gemini-3.8-flash:generateContent"])
        self.assertEqual(calls[1]["body"]["generationConfig"]["thinkingConfig"],
                         {"thinkingLevel": "low"})
        self.assertIn(f"{ALIAS} was refused, using gemini-3.8-flash from the "
                      f"model list", self.log_text())

        # Kept for the life of the process: no new list, no new refusal.
        self.analyze(title="Bose SoundLink Flex speaker, blue")
        negotiator.draft_message("Bose SoundLink Flex speaker", 60.0, 40.0,
                                 None, [])
        self.assertEqual(self.server.list_calls, 2)
        later = [c["path"].rsplit("/", 1)[-1] for c in self.gemini_calls()[2:]]
        self.assertEqual(later, ["gemini-3.8-flash:generateContent"] * 2)

    def test_no_flash_model_in_the_list(self):
        self.server.open_models = set()
        self.server.list_has_flash = False
        status, page = self.analyze()
        self.assertEqual(status, 200)
        self.assertIn(msg.PHOTO_NO_MODEL, page)

    def test_cut_off_answer(self):
        self.server.gemini = "cut_off"
        status, page = self.analyze()
        self.assertEqual(status, 200)
        self.assertIn(msg.PHOTO_CUT_OFF, page)
        self.assertNotIn(RAW_MARKER, page)
        self.assertIn("Photo check failed: finish reason MAX_TOKENS", self.log_text())

    def test_blocked_answers(self):
        for mode in ("blocked", "blocked_finish"):
            with self.subTest(mode=mode):
                self.server.gemini = mode
                status, page = self.analyze()
                self.assertEqual(status, 200)
                self.assertIn(msg.PHOTO_BLOCKED, page)


class ThinkingSettingPerModel(unittest.TestCase):

    def test_lowest_setting_each_model_takes(self):
        import gemini
        cases = {
            ALIAS: {"thinkingLevel": "low"},
            "gemini-3.8-flash": {"thinkingLevel": "low"},
            "gemini-3.7-flash": {"thinkingLevel": "low"},
            "gemini-3.6-flash": {"thinkingLevel": "minimal"},
            "gemini-3.5-flash": {"thinkingLevel": "minimal"},
            "gemini-3-flash": {"thinkingLevel": "minimal"},
            "gemini-2.5-flash": {"thinkingBudget": 0},
        }
        for model, expected in cases.items():
            with self.subTest(model=model):
                self.assertEqual(gemini.thinking_config(model), expected)


class DraftCall(RealModeTest):

    def setUp(self):
        super().setUp()
        # Every model answers here, so the cut-off and blocked tests reach
        # the answer they're about.
        self.server.open_models = {ALIAS, "gemini-2.5-flash"}

    def draft(self):
        return negotiator.draft_message("Bose SoundLink Flex speaker", 60.0,
                                        40.0, "Light scuffs",
                                        ["Ask if the cable comes with it"])

    def test_same_model_thinking_and_room_in_plain_text(self):
        self.assertEqual(self.draft(), DRAFT_TEXT)
        call = self.gemini_calls()[0]
        self.assertTrue(call["path"].endswith(f"/models/{ALIAS}:generateContent"))
        config = call["body"]["generationConfig"]
        self.assertEqual(config["thinkingConfig"], {"thinkingLevel": "low"})
        self.assertGreaterEqual(config["maxOutputTokens"], 2048)
        self.assertNotIn("responseMimeType", config)
        self.assertNotIn("responseJsonSchema", config)

    def test_cut_off_draft_falls_back_to_the_template(self):
        self.server.gemini = "cut_off"
        text = self.draft()
        self.assertNotEqual(text, DRAFT_TEXT[:20])
        self.assertIn("would you take $40?", text)

    def test_blocked_draft_falls_back_to_the_template(self):
        self.server.gemini = "blocked_finish"
        text = self.draft()
        self.assertNotEqual(text, DRAFT_TEXT[:20])
        self.assertIn("would you take $40?", text)


class NoPromisedFreeRequests(unittest.TestCase):

    def test_comments_promise_no_free_tier(self):
        vision = (REPO_DIR / "vision_analysis.py").read_text()
        for phrase in ("requests/day", "1,500", "free tier", "Google's free"):
            self.assertNotIn(phrase, vision)
        text = (REPO_DIR / "settings.py").read_text()
        for phrase in ("free tier", "no credit card", "no expiration",
                       "Get a free key"):
            self.assertNotIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
