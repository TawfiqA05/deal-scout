"""DEALSCOUT_DEMO_MODE in .env turns demo mode off; demo stays the default."""

import os
import unittest
from pathlib import Path
from unittest import mock

from tests import TMP_DIR
from tests.helpers import run_fresh_python

import dealscout
import ebay_api
import settings
import vision_analysis

READ_DEMO_MODE = "import dealscout, settings; print(settings.DEMO_MODE)"


def demo_mode_with_env_file(contents):
    """Start a fresh interpreter whose .env holds the given text and report
    settings.DEMO_MODE after importing the app."""
    env_file = TMP_DIR / f"switch-{abs(hash(contents))}.env"
    env_file.write_text(contents)
    return run_fresh_python(READ_DEMO_MODE, {
        "DEALSCOUT_ENV_FILE": str(env_file),
        "DEALSCOUT_DB_PATH": str(TMP_DIR / "switch.db"),
        "DEALSCOUT_UPLOADS_DIR": str(TMP_DIR / "uploads"),
    }).strip()


class DemoSwitchInEnvFile(unittest.TestCase):

    def test_off_in_env_file_turns_demo_off(self):
        self.assertEqual(demo_mode_with_env_file("DEALSCOUT_DEMO_MODE=off\n"), "False")

    def test_on_in_env_file_keeps_demo_on(self):
        self.assertEqual(demo_mode_with_env_file("DEALSCOUT_DEMO_MODE=on\n"), "True")

    def test_demo_is_the_default(self):
        self.assertEqual(demo_mode_with_env_file("GEMINI_API_KEY=placeholder\n"), "True")

    def test_shell_value_wins_over_env_file(self):
        env_file = TMP_DIR / "switch-shell.env"
        env_file.write_text("DEALSCOUT_DEMO_MODE=off\n")
        out = run_fresh_python(READ_DEMO_MODE, {
            "DEALSCOUT_ENV_FILE": str(env_file),
            "DEALSCOUT_DB_PATH": str(TMP_DIR / "switch.db"),
            "DEALSCOUT_UPLOADS_DIR": str(TMP_DIR / "uploads"),
            "DEALSCOUT_DEMO_MODE": "on",
        })
        self.assertEqual(out.strip(), "True")

    def test_env_example_names_the_switch(self):
        example = (Path(dealscout.APP_DIR) / ".env.example").read_text()
        self.assertIn("DEALSCOUT_DEMO_MODE=on", example)
        self.assertNotIn("settings.py", example)


class MessagesPointAtTheSwitch(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.object(settings, "DEMO_MODE", False)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for key in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "GEMINI_API_KEY"):
            os.environ.pop(key, None)
        ebay_api._token_cache.update(token=None, expires=0)

    def test_ebay_keys_message(self):
        with self.assertRaises(ebay_api.EbayError) as caught:
            ebay_api.search_comps("Makita impact driver", 60.0)
        message = str(caught.exception)
        self.assertIn("DEALSCOUT_DEMO_MODE=on", message)
        self.assertNotIn("settings.py", message)

    def test_gemini_key_message(self):
        report = vision_analysis.analyze("Makita impact driver", 60.0, "", [])
        self.assertIn("DEALSCOUT_DEMO_MODE=on", report["error"])
        self.assertNotIn("settings.py", report["error"])

    def test_startup_message(self):
        with mock.patch.object(settings, "DEMO_MODE", True):
            message = dealscout.startup_message()
        self.assertIn("DEALSCOUT_DEMO_MODE=off", message)
        self.assertNotIn("settings.py", message)


if __name__ == "__main__":
    unittest.main()
