"""score_deal output for five fixed inputs, captured at commit 05cbe3a.
Later runs that change the profit math should change this on purpose."""

import json
import unittest
from pathlib import Path

import scoring

PINNED = json.loads((Path(__file__).parent / "scoring_pinned.json").read_text())


class ScoringIsPinned(unittest.TestCase):

    def test_five_pinned_inputs(self):
        self.assertEqual(len(PINNED), 5)
        for case in PINNED:
            given = case["input"]
            with self.subTest(asking_price=given["asking_price"]):
                got = scoring.score_deal(given["asking_price"],
                                         given["comp_prices"],
                                         given["category_guess"],
                                         given["size_class"])
                self.assertEqual(got, case["output"])


if __name__ == "__main__":
    unittest.main()
