"""Photos come in the formats Gemini takes, and all of them together stay
under Google's 20MB limit for one request."""

import html
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from tests import TMP_DIR
from tests.helpers import RealModeTest, fresh_db, local_client
from tests.test_input import PNG

import dealscout
import settings
import vision_analysis

MB = 1024 * 1024
GOOGLE_REQUEST_LIMIT = 20_000_000   # "20MB", read as the smaller number
LISTING_URL = "https://www.ebay.com/itm/Bose-SoundLink-Flex/123456789012"
FORMAT_LINE = ("Skipped '{}'. The photo check takes JPG, PNG, WebP and HEIC "
               "photos only.")
TOTAL_LINE = ("Skipped '{}' because the photos together would go over 13 MB, "
              "the most the photo check can send.")
LISTING_LINE = ("Left out some of the listing's own photos to keep the photo "
                "check under 13 MB.")
HINT = ("(save them from the listing, then add them here: up to 6 JPG, PNG, "
        "WebP or HEIC photos, 4.5 MB each and 13 MB in all)")


def photo(size, name):
    """A PNG padded out to size bytes."""
    return (io.BytesIO(PNG + b"\0" * (size - len(PNG))), name)


def inline_photos(gemini_call):
    return [p["inlineData"] for p in gemini_call["body"]["contents"][0]["parts"]
            if "inlineData" in p]


class Limits(unittest.TestCase):

    def test_total_leaves_room_under_googles_limit(self):
        encoded = (settings.MAX_TOTAL_PHOTO_BYTES + 2) // 3 * 4
        text = (len(vision_analysis.PROMPT) + vision_analysis.MAX_TITLE_CHARS
                + 3000 + 1000)   # prompt, title, description, category list
        self.assertLess(encoded + text + 64 * 1024, GOOGLE_REQUEST_LIMIT)
        self.assertEqual(dealscout.TOTAL_MB, 13)

    def test_formats_match_googles_list(self):
        self.assertEqual(dealscout.ALLOWED_PHOTO_TYPES,
                         {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"})
        self.assertEqual(set(vision_analysis._MEDIA_TYPES),
                         dealscout.ALLOWED_PHOTO_TYPES)
        self.assertEqual(set(vision_analysis._MEDIA_TYPES.values()),
                         {"image/jpeg", "image/png", "image/webp",
                          "image/heic", "image/heif"})

    def test_ebay_gif_is_not_downloaded(self):
        answer = mock.Mock(content=b"GIF89a", headers={"content-type": "image/gif"})
        answer.raise_for_status.return_value = None
        with mock.patch.object(requests, "get", return_value=answer):
            self.assertIsNone(dealscout._download_image("https://i.ebayimg.com/a.gif"))
        answer.headers = {"content-type": "image/heic"}
        with mock.patch.object(requests, "get", return_value=answer):
            self.assertEqual(dealscout._download_image("https://i.ebayimg.com/a.heic"),
                             (b"GIF89a", ".heic"))


class DemoPhotoForm(unittest.TestCase):

    def setUp(self):
        self.patcher, _ = fresh_db()
        self.addCleanup(self.patcher.stop)
        self.client = local_client()

    def post(self, photos):
        return html.unescape(self.client.post("/analyze", data={
            "title": "Makita 18V LXT cordless impact driver, tool only",
            "asking_price": "60", "photos": photos},
            content_type="multipart/form-data").get_data(as_text=True))

    def test_picker_and_hint(self):
        page = html.unescape(self.client.get("/").get_data(as_text=True))
        self.assertIn(HINT, page)
        self.assertIn('accept=".jpg,.jpeg,.png,.webp,.heic,.heif"', page)
        self.assertNotIn("gif", page.lower())

    def test_gif_and_other_formats_are_skipped(self):
        for name in ("listing.gif", "LISTING.GIF", "scan.bmp", "photo.tiff"):
            with self.subTest(name=name):
                self.assertIn(FORMAT_LINE.format(name),
                              self.post([(io.BytesIO(b"GIF89a"), name)]))


class RealModePhotos(RealModeTest):

    def post(self, photos, **form):
        form.setdefault("title", "Bose SoundLink Flex Bluetooth speaker")
        form.setdefault("asking_price", "35")
        response = self.client.post("/analyze", data={**form, "photos": photos},
                                    content_type="multipart/form-data")
        return html.unescape(response.get_data(as_text=True))

    def test_heic_and_heif_reach_gemini(self):
        page = self.post([photo(2000, "IMG_0412.HEIC"), photo(2000, "back.heif")])
        self.assertNotIn("Skipped", page)
        sent = inline_photos(self.gemini_calls()[0])
        self.assertEqual([p["mimeType"] for p in sent], ["image/heic", "image/heif"])

    def test_gif_never_reaches_gemini(self):
        page = self.post([photo(2000, "front.png"), photo(2000, "spin.gif")])
        self.assertIn(FORMAT_LINE.format("spin.gif"), page)
        sent = inline_photos(self.gemini_calls()[0])
        self.assertEqual([p["mimeType"] for p in sent], ["image/png"])

    def test_photos_past_the_total_are_skipped(self):
        page = self.post([photo(4 * MB, f"{n}.jpg") for n in "abcd"])
        self.assertIn(TOTAL_LINE.format("d.jpg"), page)
        for name in "abc":
            self.assertNotIn(f"Skipped '{name}.jpg'", page)
        self.assertEqual(len(inline_photos(self.gemini_calls()[0])), 3)

    def test_a_smaller_photo_after_a_skipped_one_still_fits(self):
        page = self.post([photo(4 * MB, "a.jpg"), photo(4 * MB, "b.jpg"),
                          photo(4 * MB, "c.jpg"), photo(4 * MB, "d.jpg"),
                          photo(MB // 2, "e.jpg")])
        self.assertIn(TOTAL_LINE.format("d.jpg"), page)
        self.assertNotIn("Skipped 'e.jpg'", page)
        self.assertEqual(len(inline_photos(self.gemini_calls()[0])), 4)

    def test_biggest_request_stays_under_20mb(self):
        just_under = settings.MAX_TOTAL_PHOTO_BYTES - 3 * 1000
        sizes = [dealscout.MAX_PHOTO_BYTES, dealscout.MAX_PHOTO_BYTES,
                 just_under - 2 * dealscout.MAX_PHOTO_BYTES]
        page = self.post([photo(s, f"{n}.png") for n, s in enumerate(sizes)],
                         title="Bose speaker " + "x" * 200_000,
                         description="Works fine. " * 2000)
        self.assertNotIn("Skipped", page)
        call = self.gemini_calls()[0]
        self.assertEqual(len(inline_photos(call)), 3)
        self.assertLess(call["length"], GOOGLE_REQUEST_LIMIT)
        self.assertGreater(call["length"], 17_000_000)   # the photos did go

    def test_six_full_size_photos_stay_under_20mb(self):
        # Before this run these went out as about 36MB.
        page = self.post([photo(dealscout.MAX_PHOTO_BYTES, f"{n}.jpg")
                          for n in range(6)])
        for n in (2, 3, 4, 5):
            self.assertIn(TOTAL_LINE.format(f"{n}.jpg"), page)
        call = self.gemini_calls()[0]
        self.assertEqual(len(inline_photos(call)), 2)
        self.assertLess(call["length"], GOOGLE_REQUEST_LIMIT)

    def test_listing_photos_left_out_past_the_total(self):
        fill = [photo(dealscout.MAX_PHOTO_BYTES, "a.png"),
                photo(dealscout.MAX_PHOTO_BYTES, "b.png"),
                photo(settings.MAX_TOTAL_PHOTO_BYTES
                      - 2 * dealscout.MAX_PHOTO_BYTES - 10, "c.png")]
        page = self.post(fill, ebay_url=LISTING_URL)
        self.assertIn(LISTING_LINE, page)
        self.assertEqual(len(self.server.calls_to("i.ebayimg.com")), 1)
        self.assertEqual(len(inline_photos(self.gemini_calls()[0])), 3)

    def test_listing_photo_fits_when_there_is_room(self):
        page = self.post([photo(2000, "a.png")], ebay_url=LISTING_URL)
        self.assertNotIn(LISTING_LINE, page)
        self.assertEqual(len(inline_photos(self.gemini_calls()[0])), 2)

    def test_vision_check_holds_the_total_by_itself(self):
        folder = Path(tempfile.mkdtemp(dir=TMP_DIR))
        paths = []
        for n in range(4):
            path = folder / f"{n}.png"
            path.write_bytes(PNG + b"\0" * (4 * MB))
            paths.append(path)
        vision_analysis.analyze("Bose speaker", 35.0, "", paths)
        self.assertEqual(len(inline_photos(self.gemini_calls()[0])), 3)


if __name__ == "__main__":
    unittest.main()
