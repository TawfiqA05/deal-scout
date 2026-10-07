"""Demo mode makes no network calls, start to finish."""

import io
import unittest
import webbrowser
from unittest import mock

import requests

from tests.helpers import fresh_db
from tests.test_input import PNG

import dealscout
import settings


class DemoModeStaysOffline(unittest.TestCase):

    def setUp(self):
        self.patcher, _ = fresh_db()
        self.client = dealscout.app.test_client()

    def tearDown(self):
        self.patcher.stop()

    def test_every_demo_page_runs_without_the_network(self):
        self.assertTrue(settings.DEMO_MODE)
        with mock.patch.object(requests.Session, "request") as http, \
                mock.patch.object(webbrowser, "open") as browser:
            pages = [
                self.client.get("/"),
                self.client.post("/analyze", data={
                    "title": "Nintendo Switch OLED console, white",
                    "asking_price": "150", "size_class": "small",
                    "photos": (io.BytesIO(PNG), "switch.png")},
                    content_type="multipart/form-data"),
                self.client.post("/analyze", data={
                    "ebay_url": "https://www.ebay.com/itm/123456789012"}),
                self.client.get("/history"),
            ]
        for page in pages:
            self.assertEqual(page.status_code, 200)
        http.assert_not_called()
        browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
