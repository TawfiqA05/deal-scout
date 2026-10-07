"""Uploads are sized before they're saved, the whole request is capped, and
the photos a request saved are gone when it ends, even when it fails.
Files already in the uploads folder are left alone."""

import html
import io
import threading
import unittest
from pathlib import Path
from unittest import mock

import requests
from werkzeug.datastructures import FileStorage
from werkzeug.serving import make_server

from tests import TMP_DIR
from tests.helpers import BASE_URL, RealModeTest, fresh_db, local_client
from tests.test_input import PNG

import database
import dealscout
import scoring
import vision_analysis

MB = 1024 * 1024
TOO_BIG = ("That upload was over 28 MB, so nothing was analyzed. Pick fewer "
           "or smaller photos and try again.")
ONE_TOO_BIG = ("Skipped 'huge.jpg' because it's over 4.5 MB. Use a smaller "
               "copy or a screenshot of it.")
FORM = {"title": "Bose SoundLink Flex Bluetooth speaker", "asking_price": "35",
        "size_class": "small"}
LISTING_URL = "https://www.ebay.com/itm/Bose-SoundLink-Flex/123456789012"


def photo(size, name):
    return (io.BytesIO(PNG + b"\0" * (size - len(PNG))), name)


class KeepsOldFiles:
    """Puts a file in the temp uploads folder before each test and checks
    after it that the file is still there, unchanged, and that the request
    left nothing else behind."""

    def setUp(self):
        super().setUp()
        self.folder = Path(dealscout.UPLOAD_DIR)
        self.assertTrue(self.folder.is_relative_to(TMP_DIR))
        self.folder.mkdir(parents=True, exist_ok=True)
        for leftover in self.folder.iterdir():
            leftover.unlink()
        self.old_file = self.folder / "from-an-earlier-run.jpg"
        self.old_file.write_bytes(b"an older photo")

    def assert_only_old_file_left(self):
        self.assertEqual(list(self.folder.iterdir()), [self.old_file])
        self.assertEqual(self.old_file.read_bytes(), b"an older photo")


class Sizes(KeepsOldFiles, unittest.TestCase):

    def setUp(self):
        self.patcher, _ = fresh_db()
        self.addCleanup(self.patcher.stop)
        self.client = local_client()
        super().setUp()

    def post(self, photos, **kwargs):
        response = self.client.post("/analyze", data={**FORM, "photos": photos},
                                    content_type="multipart/form-data", **kwargs)
        return response.status_code, html.unescape(response.get_data(as_text=True))

    def test_big_photo_is_never_written(self):
        with mock.patch.object(FileStorage, "save",
                               autospec=True, wraps=FileStorage.save) as save:
            status, page = self.post([photo(5 * MB, "huge.jpg"),
                                      photo(2000, "small.png")])
        self.assertEqual(status, 200)
        self.assertIn(ONE_TOO_BIG, page)
        saved_names = [call.args[0].filename for call in save.call_args_list]
        self.assertEqual(saved_names, ["small.png"])
        self.assert_only_old_file_left()

    def test_photo_over_the_total_is_never_written(self):
        with mock.patch.object(FileStorage, "save",
                               autospec=True, wraps=FileStorage.save) as save:
            self.post([photo(4 * MB, f"{n}.jpg") for n in "abcd"])
        self.assertEqual([c.args[0].filename for c in save.call_args_list],
                         ["a.jpg", "b.jpg", "c.jpg"])
        self.assert_only_old_file_left()

    def test_request_over_28mb_is_refused_in_the_banner(self):
        status, page = self.post([photo(29 * MB, "huge.jpg")])
        self.assertEqual(status, 413)
        self.assertIn(f'<div class="banner banner-error">{TOO_BIG}</div>', page)
        self.assertIn('name="form_token"', page)
        self.assertNotIn("stamp stamp-", page)
        self.assertEqual(database.get_history(), [])
        self.assert_only_old_file_left()

    def test_six_full_photos_fit_under_the_cap(self):
        status, page = self.post([photo(dealscout.MAX_PHOTO_BYTES, f"{n}.jpg")
                                  for n in range(6)])
        self.assertEqual(status, 200)
        self.assertNotIn(TOO_BIG, page)
        self.assertEqual(dealscout.REQUEST_MB, 28)
        self.assertEqual(dealscout.app.config["MAX_CONTENT_LENGTH"],
                         dealscout.MAX_REQUEST_BYTES)
        self.assert_only_old_file_left()

    def test_refused_post_saves_nothing(self):
        status, _ = self.post([photo(2000, "a.png")],
                              headers={"Origin": "https://shop.example"})
        self.assertEqual(status, 403)
        response = self.client.post(
            "/analyze", data={**FORM, "form_token": "wrong",
                              "photos": photo(2000, "a.png")},
            content_type="multipart/form-data")
        self.assertEqual(response.status_code, 403)
        self.assert_only_old_file_left()


class PhotosGoWhenTheRequestEnds(KeepsOldFiles, RealModeTest):

    def post(self, photos, **form):
        response = self.client.post("/analyze",
                                    data={**FORM, **form, "photos": photos},
                                    content_type="multipart/form-data")
        return response.status_code

    def test_photos_are_there_during_the_check_and_gone_after(self):
        seen = []
        real_analyze = vision_analysis.analyze

        def spy(title, price, description, paths):
            seen.extend((Path(p), Path(p).exists()) for p in paths)
            return real_analyze(title, price, description, paths)

        with mock.patch.object(vision_analysis, "analyze", side_effect=spy):
            status = self.post([photo(2000, "front.png"), photo(3000, "back.jpg")],
                               ebay_url=LISTING_URL)
        self.assertEqual(status, 200)
        # Two uploads plus the listing's own photo, all on disk for the check.
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(existed for _, existed in seen))
        self.assertTrue(all(p.parent == self.folder for p, _ in seen))
        self.assertEqual(len(self.gemini_calls()), 1)
        self.assert_only_old_file_left()

    def test_photos_go_when_the_analysis_crashes(self):
        boom = RuntimeError("scoring broke")
        with mock.patch.object(scoring, "score_deal", side_effect=boom), \
                self.assertLogs(dealscout.app.logger, "ERROR"):
            status = self.post([photo(2000, "front.png")], ebay_url=LISTING_URL)
        self.assertEqual(status, 500)
        self.assert_only_old_file_left()

    def test_photos_go_when_the_photo_check_fails(self):
        self.server.gemini = "http_500"
        status = self.post([photo(2000, "front.png")])
        self.assertEqual(status, 200)
        self.assert_only_old_file_left()

    def test_photos_go_when_the_comp_search_fails(self):
        self.server.ebay = {"search": "http_500"}
        status = self.post([photo(2000, "front.png")])
        self.assertEqual(status, 200)
        self.assert_only_old_file_left()


class RealServerRefusesBigRequests(unittest.TestCase):
    """The real Werkzeug server, so the 413 is what a browser would get."""

    def setUp(self):
        self.patcher, _ = fresh_db()
        self.addCleanup(self.patcher.stop)
        server = make_server("127.0.0.1", 0, dealscout.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_port}"

    def test_over_28mb_gets_the_banner(self):
        response = requests.post(
            self.base + "/analyze",
            data={**FORM, "form_token": dealscout.FORM_TOKEN},
            files={"photos": ("huge.jpg", b"\0" * (29 * MB), "image/jpeg")},
            timeout=20)
        self.assertEqual(response.status_code, 413)
        self.assertIn(TOO_BIG, html.unescape(response.text))
        self.assertEqual(database.get_history(), [])


if __name__ == "__main__":
    unittest.main()
