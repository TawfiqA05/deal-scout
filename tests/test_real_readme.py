"""The README and .env.example say how to try real mode, including the
step eBay requires before production keys work."""

import re
import unittest

from tests import REPO_DIR


def flat(text):
    return re.sub(r"\s+", " ", text)


class RealModeSteps(unittest.TestCase):

    def test_readme_has_the_steps(self):
        readme = flat((REPO_DIR / "README.md").read_text())
        for part in (
                "Here's how to run it with your own keys.",
                "Under Application Keys, create a Production keyset (not Sandbox).",
                "eBay won't turn on a new production keyset until you answer "
                "its marketplace account deletion notice.",
                'turn on "Not persisting eBay data" and choose the reason '
                "that fits.",
                "Deal Scout keeps listing titles, prices and descriptions in "
                "its local history, but no eBay account data.",
                "Get a Gemini API key at aistudio.google.com.",
                "change `DEALSCOUT_DEMO_MODE=on` to `DEALSCOUT_DEMO_MODE=off`.",
                "eBay's default limit for the Browse API is 5,000 calls a day.",
                "The Gemini key goes in a request header"):
            self.assertIn(part, readme)

    def test_env_example_points_at_the_steps(self):
        example = (REPO_DIR / ".env.example").read_text()
        self.assertIn("# eBay Browse API keys from developer.ebay.com. "
                      "Production keys only work after the account deletion "
                      "step in the README.", example)
        self.assertIn("# Google Gemini key from aistudio.google.com.", example)
        for phrase in ("free tier", "no credit card", "(free", "approval needed"):
            self.assertNotIn(phrase, example)


if __name__ == "__main__":
    unittest.main()
