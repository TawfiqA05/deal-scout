"""Bad input and a broken uploads folder get a message, not a crash."""

import io
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import TMP_DIR
from tests.helpers import fresh_db

import database
import dealscout
import scoring

FORM_ERROR = "Please enter at least a title and an asking price"
UPLOAD_WARNING = "Couldn&#39;t save the uploaded photos, so the check ran without them."
ERROR_LINE = ("Deal Scout hit an error and couldn't finish that. The details "
              "are in the terminal where it's running.")

# Smallest valid PNG: 1x1 pixel.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


class AppTestCase(unittest.TestCase):

    def setUp(self):
        self.patcher, _ = fresh_db()
        self.client = dealscout.app.test_client()

    def tearDown(self):
        self.patcher.stop()

    def analyze(self, **form):
        form.setdefault("title", "Makita 18V LXT cordless impact driver, tool only")
        form.setdefault("asking_price", "60")
        return self.client.post("/analyze", data=form,
                                content_type="multipart/form-data")


class PricesThatAreNotNumbers(AppTestCase):

    def test_nan_inf_and_huge_prices_get_the_form_error(self):
        for price in ("nan", "NaN", "inf", "-inf", "Infinity", "1e400",
                      "1000000.01", "1e308"):
            with self.subTest(price=price):
                response = self.analyze(asking_price=price)
                self.assertEqual(response.status_code, 200)
                self.assertIn(FORM_ERROR, response.get_data(as_text=True))
        self.assertEqual(database.get_history(), [])

    def test_a_million_is_still_allowed(self):
        response = self.analyze(asking_price="1000000")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(FORM_ERROR, response.get_data(as_text=True))
        self.assertEqual(len(database.get_history()), 1)

    def test_no_dollar_inf_on_the_page(self):
        html = self.analyze(asking_price="inf").get_data(as_text=True)
        self.assertNotIn("$inf", html)


class UploadsFolderProblems(AppTestCase):

    def analyze_with_photo(self):
        return self.analyze(photos=(io.BytesIO(PNG), "listing.png"))

    def test_missing_folder_is_made_again(self):
        folder = Path(tempfile.mkdtemp(dir=TMP_DIR)) / "uploads"
        with mock.patch.object(dealscout, "UPLOAD_DIR", folder):
            response = self.analyze_with_photo()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(list(folder.iterdir())), 1)

    def test_folder_that_cannot_be_made_gives_a_warning(self):
        blocker = Path(tempfile.mkdtemp(dir=TMP_DIR)) / "a-file"
        blocker.write_text("not a folder")
        with mock.patch.object(dealscout, "UPLOAD_DIR", blocker / "uploads"):
            response = self.analyze_with_photo()
        self.assertEqual(response.status_code, 200)
        self.assertIn(UPLOAD_WARNING, response.get_data(as_text=True))
        self.assertEqual(len(database.get_history()), 1)

    @unittest.skipIf(os.geteuid() == 0, "root can write to read-only folders")
    def test_read_only_folder_gives_a_warning(self):
        folder = Path(tempfile.mkdtemp(dir=TMP_DIR))
        folder.chmod(stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(folder.chmod, stat.S_IRWXU)
        with mock.patch.object(dealscout, "UPLOAD_DIR", folder):
            response = self.analyze_with_photo()
        self.assertEqual(response.status_code, 200)
        self.assertIn(UPLOAD_WARNING, response.get_data(as_text=True))
        self.assertEqual(len(database.get_history()), 1)


class ErrorPage(AppTestCase):

    def test_unexpected_error_shows_one_plain_line(self):
        boom = RuntimeError("secret detail from deep inside")
        with mock.patch.object(scoring, "score_deal", side_effect=boom), \
                self.assertLogs(dealscout.app.logger, "ERROR"):
            response = self.analyze()
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Something went wrong", html)
        self.assertIn(ERROR_LINE, html)
        for leak in ("Traceback", "RuntimeError", "secret detail", "File \""):
            self.assertNotIn(leak, html)

    def test_unknown_page(self):
        response = self.client.get("/no-such-page")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 404)
        self.assertIn("Page not found", html)
        self.assertIn("There's no page at this address.", html)
        self.assertIn("Back to Deal Scout", html)

    def test_history_failure_also_gets_the_page(self):
        with mock.patch.object(database, "get_history",
                               side_effect=OSError("disk gone")), \
                self.assertLogs(dealscout.app.logger, "ERROR"):
            response = self.client.get("/history")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 500)
        self.assertIn(ERROR_LINE, html)
        self.assertNotIn("disk gone", html)


if __name__ == "__main__":
    unittest.main()
