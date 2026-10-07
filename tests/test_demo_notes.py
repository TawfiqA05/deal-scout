"""Demo notes, comp titles and the sample listing fit the item and read right."""

import re
import unittest

import dealscout
import ebay_api
import negotiator
import settings
import vision_analysis
from tests.helpers import fresh_db

# Inputs a later run turns into tappable examples. Each gives one verdict.
THREE_DEMO_INPUTS = [
    ({"title": "Makita 18V LXT cordless impact driver, tool only",
      "asking_price": "60", "size_class": "medium"}, "BUY"),
    ({"title": "Nintendo Switch OLED console, white",
      "asking_price": "150", "size_class": "small"}, "NEGOTIATE"),
    ({"title": "Sony WH-1000XM4 wireless headphones",
      "asking_price": "180", "size_class": "small"}, "PASS"),
]

DRILL_WORDS = re.compile(r"battery|charger|charge|drill|housing", re.I)


def verdict_in(html):
    match = re.search(r'class="stamp stamp-(buy|negotiate|pass)"', html)
    return match.group(1).upper() if match else None


class DemoNotesFitTheItem(unittest.TestCase):

    def setUp(self):
        self.assertTrue(settings.DEMO_MODE)

    def notes(self, title):
        report = vision_analysis.analyze(title, 100.0, "", [])
        return report, [report["condition"], *report["red_flags"],
                        *report["missing_info"]]

    def test_sneakers_get_sneaker_notes(self):
        report, notes = self.notes("Nike Air Jordan 1 Retro High OG, size 10")
        self.assertEqual(report["category_guess"], "sneakers")
        for note in notes:
            self.assertNotRegex(note, DRILL_WORDS)
        self.assertTrue(any("size tag" in n for n in notes))

    def test_unknown_items_get_general_notes(self):
        report, notes = self.notes("Mid-century oak side table")
        self.assertEqual(report["category_guess"], "default")
        for note in notes:
            self.assertNotRegex(note, DRILL_WORDS)

    def test_categories_come_from_the_fee_table(self):
        titles = ["Makita 18V LXT cordless impact driver, tool only",
                  "Nintendo Switch OLED console, white",
                  "Nike Air Jordan 1 Retro High OG, size 10",
                  "Sony WH-1000XM4 wireless headphones",
                  "Mid-century oak side table"]
        categories = {self.notes(t)[0]["category_guess"] for t in titles}
        self.assertEqual(len(categories), 5)
        self.assertLessEqual(categories, set(settings.EBAY_CATEGORY_FEES))

    def test_notes_keep_the_demo_prefix(self):
        for title in ("Makita impact driver", "Vintage Pyrex bowl"):
            for note in self.notes(title)[1]:
                self.assertTrue(note.startswith("DEMO: "), note)

    def test_resale_title_is_the_item_title(self):
        report, _ = self.notes("Sony WH-1000XM4 wireless headphones")
        self.assertEqual(report["resale_title_suggestion"],
                         "Sony WH-1000XM4 wireless headphones")

    def test_draft_message_fits_the_item(self):
        draft = negotiator.draft_message(
            "Nike Air Jordan 1 Retro High OG, size 10", 150.0, 120.0,
            None, [])
        self.assertIn("$120", draft)
        self.assertNotRegex(draft, DRILL_WORDS)
        self.assertNotIn("—", draft)


class DemoCompTitles(unittest.TestCase):

    def test_titles_read_like_listings(self):
        title = "Sony WH-1000XM4 wireless headphones"
        for comp in ebay_api.search_comps(title, 180.0):
            self.assertNotIn("DEMO", comp["title"])
            self.assertTrue(comp["title"].startswith(title), comp["title"])
            self.assertLessEqual(len(comp["title"]), 80)

    def test_long_titles_are_cut_at_a_word(self):
        title = ("Vintage Pyrex Butterprint mixing bowl set of four with the "
                 "original box and lids, excellent")
        words = set(title.replace(",", "").split()) | {
            "-", "Used", "Pre-Owned", "Good", "Excellent", "Very",
            "Condition", "Light", "Wear", "Free", "Fast", "Shipping", "Clean"}
        for comp in ebay_api.search_comps(title, 40.0):
            self.assertLessEqual(len(comp["title"]), 80)
            for word in comp["title"].replace(",", "").split():
                self.assertIn(word, words, comp["title"])
            self.assertNotRegex(comp["title"], r"\b(with|the|of)( -|$)")

    def test_endings_use_a_plain_hyphen(self):
        for comp in ebay_api.search_comps("Makita impact driver", 60.0):
            self.assertNotRegex(comp["title"], "[–—]")

    def test_sample_listing_from_any_link(self):
        first = ebay_api.fetch_listing_from_url("https://www.ebay.com/itm/123456789012")
        second = ebay_api.fetch_listing_from_url("anything at all")
        self.assertEqual(first, second)
        self.assertTrue(first["title"].startswith("DEMO: "))
        self.assertIn("(sample listing)", first["title"])


class DemoPages(unittest.TestCase):

    def setUp(self):
        self.patcher, _ = fresh_db()
        self.client = dealscout.app.test_client()

    def tearDown(self):
        self.patcher.stop()

    def test_link_box_says_links_give_the_sample(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("any eBay link loads the same sample listing", page)

    def test_link_note_is_hidden_in_real_mode(self):
        from unittest import mock
        with mock.patch.object(settings, "DEMO_MODE", False):
            page = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("any eBay link loads the same sample listing", page)

    def test_comparables_panel_has_no_demo_titles(self):
        html = self.client.post("/analyze", data=THREE_DEMO_INPUTS[0][0]).get_data(as_text=True)
        comps = html.split('class="comps"')[1].split("</ul>")[0]
        self.assertNotIn("DEMO", comps)
        self.assertIn("Makita 18V LXT cordless impact driver", comps)

    def test_history_says_other_for_the_general_set(self):
        self.client.post("/analyze", data={"title": "Mid-century oak side table",
                                           "asking_price": "80"})
        page = self.client.get("/history").get_data(as_text=True)
        self.assertIn("<strong>Category guess:</strong> other", page)
        self.assertNotIn("<strong>Category guess:</strong> default", page)

    def test_three_demo_inputs_give_each_verdict(self):
        for form, want in THREE_DEMO_INPUTS:
            with self.subTest(title=form["title"]):
                html = self.client.post("/analyze", data=form).get_data(as_text=True)
                self.assertEqual(verdict_in(html), want)


if __name__ == "__main__":
    unittest.main()
