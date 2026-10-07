"""Demo comps are priced from the asking price, the same way every time."""

import random
import unittest

import ebay_api
import settings


class DemoPricesFollowAskingPrice(unittest.TestCase):

    def setUp(self):
        self.assertTrue(settings.DEMO_MODE)

    def prices(self, query, asking):
        return [c["price"] for c in ebay_api.search_comps(query, asking)]

    def test_comps_scale_with_asking_price(self):
        low_ratio, high_ratio = ebay_api.DEMO_PRICE_RATIO
        for asking in (20.0, 150.0, 2000.0):
            with self.subTest(asking=asking):
                prices = self.prices("Bose SoundLink Flex speaker", asking)
                self.assertEqual(len(prices), 14)
                self.assertGreaterEqual(min(prices),
                                        round(asking * low_ratio * 0.75, 2))
                self.assertLessEqual(max(prices),
                                     round(asking * high_ratio * 1.35, 2))

    def test_expensive_items_are_not_always_pass(self):
        # At 05cbe3a comps topped out near $216, so $400 was always PASS.
        prices = self.prices("Canon EOS R6 body", 400.0)
        self.assertGreater(max(prices), 400.0)

    def test_same_input_gives_same_comps(self):
        self.assertEqual(ebay_api.search_comps("Fender Mustang amp", 90.0),
                         ebay_api.search_comps("Fender Mustang amp", 90.0))

    def test_price_is_part_of_the_seed(self):
        self.assertNotEqual(self.prices("Fender Mustang amp", 90.0),
                            self.prices("Fender Mustang amp", 91.0))

    def test_global_random_is_left_alone(self):
        random.seed(1234)
        expected = [random.random() for _ in range(3)]
        random.seed(1234)
        ebay_api.search_comps("Fender Mustang amp", 90.0)
        self.assertEqual([random.random() for _ in range(3)], expected)


if __name__ == "__main__":
    unittest.main()
