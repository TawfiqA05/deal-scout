"""The code names the tools it really uses and talks to developers plainly."""

import re
import unittest

from tests import REPO_DIR

SOURCE_FILES = sorted(REPO_DIR.glob("*.py"))


class SourceWording(unittest.TestCase):

    def read_all(self):
        self.assertGreaterEqual(len(SOURCE_FILES), 7)
        return {path.name: path.read_text() for path in SOURCE_FILES}

    def test_no_old_model_names(self):
        for name, text in self.read_all().items():
            for old in ("Claude Vision", "Anthropic"):
                self.assertNotIn(old, text, name)

    def test_no_comments_written_for_non_coders(self):
        for name, text in self.read_all().items():
            for old in ("No coding knowledge", "You never need to touch",
                        "with any text editor"):
                self.assertNotIn(old, text, name)

    def test_no_numbered_box_banners(self):
        for name, text in self.read_all().items():
            self.assertIsNone(re.search(r"#\s*─+\s*\d+\.", text), name)
            self.assertNotIn("# ──", text, name)

    def test_no_message_says_to_edit_settings_for_demo_mode(self):
        texts = self.read_all()
        for doc in ("README.md", ".env.example"):
            texts[doc] = (REPO_DIR / doc).read_text()
        for name, text in texts.items():
            self.assertNotRegex(text, r"DEMO_MODE[^\n]*\n?[^\n]*settings\.py", name)
            self.assertNotRegex(text, r"[Ss]et `?DEMO_MODE = False", name)


if __name__ == "__main__":
    unittest.main()
