"""Only the tool's own page can use it: a wrong Host or another site's
Origin is refused, and every form post needs the token from the page."""

import html
import re
import threading
import unittest

import requests
from werkzeug.serving import make_server

from tests.helpers import BASE_URL, fresh_db, local_client, run_fresh_python

import database
import dealscout

WRONG_HOST_HEADING = "Not at this address"
FORM = {"title": "Makita 18V LXT cordless impact driver, tool only",
        "asking_price": "60", "size_class": "medium"}


def wrong_host_line(port):
    return (f"Deal Scout only answers at http://localhost:{port}. Open it "
            f"there and try again.")


class GuardTestCase(unittest.TestCase):

    def setUp(self):
        self.patcher, _ = fresh_db()
        self.addCleanup(self.patcher.stop)
        self.client = local_client()

    def page(self, response):
        return response.status_code, html.unescape(response.get_data(as_text=True))


class WrongHost(GuardTestCase):

    def test_other_hosts_get_the_error_page_without_the_form(self):
        for host in ("deals.example:5001", "localhost:5002", "localhost",
                     "192.168.1.20:5001", "127.0.0.1.deals.example:5001",
                     "deals.example"):
            for method, path in (("get", "/"), ("get", "/history"),
                                 ("post", "/analyze"), ("get", "/static/style.css")):
                with self.subTest(host=host, path=path):
                    response = getattr(self.client, method)(
                        path, data=FORM if method == "post" else None,
                        headers={"Host": host})
                    status, page = self.page(response)
                    self.assertEqual(status, 400)
                    self.assertIn(WRONG_HOST_HEADING, page)
                    self.assertIn(wrong_host_line(5001), page)
                    self.assertNotIn(dealscout.FORM_TOKEN, page)
                    self.assertNotIn("form_token", page)
        self.assertEqual(database.get_history(), [])

    def test_plain_flask_client_is_refused(self):
        # Host "localhost" with no port, the way Flask's client sends it.
        status, page = self.page(dealscout.app.test_client().get("/"))
        self.assertEqual(status, 400)
        self.assertIn(WRONG_HOST_HEADING, page)

    def test_each_local_name_on_the_port_works(self):
        # Werkzeug's test client can't read a port from an IPv6 base
        # address, so each name goes in the Host header on port 5001.
        for host in ("localhost:5001", "127.0.0.1:5001", "[::1]:5001",
                     "LOCALHOST:5001"):
            with self.subTest(host=host):
                status, page = self.page(self.client.get(
                    "/", headers={"Host": host}))
                self.assertEqual(status, 200)
                self.assertIn('name="form_token"', page)
                status, page = self.page(self.client.post(
                    "/analyze", data=FORM, headers={"Host": host}))
                self.assertEqual(status, 200)
                self.assertIn("stamp stamp-buy", page)
        self.assertEqual(len(database.get_history()), 4)

    def test_another_port_follows_the_server(self):
        # Started on 8123, the tool answers there and names 8123.
        status, _ = self.page(self.client.get(
            "/", base_url="http://127.0.0.1:8123"))
        self.assertEqual(status, 200)
        status, page = self.page(self.client.get(
            "/", base_url="http://127.0.0.1:8123",
            headers={"Host": "localhost:5001"}))
        self.assertEqual(status, 400)
        self.assertIn(wrong_host_line(8123), page)
        self.assertNotIn("5001", page)


class OtherSiteOrigin(GuardTestCase):

    def test_other_origins_are_refused_in_the_banner(self):
        for origin in ("https://shop.example", "http://localhost:3000",
                       "null", "http://127.0.0.1:5001.deals.example",
                       "https://localhost:5001"):
            with self.subTest(origin=origin):
                status, page = self.page(self.client.post(
                    "/analyze", data=FORM, headers={"Origin": origin}))
                self.assertEqual(status, 403)
                self.assertIn('<div class="banner banner-error">Deal Scout '
                              'turned that down because it came from another '
                              'website. Use the form on this page instead.</div>',
                              page)
                self.assertNotIn("stamp stamp-", page)
        self.assertEqual(database.get_history(), [])

    def test_own_origins_are_fine(self):
        for origin in (BASE_URL, "http://127.0.0.1:5001", "http://[::1]:5001"):
            with self.subTest(origin=origin):
                status, page = self.page(self.client.post(
                    "/analyze", data=FORM, headers={"Origin": origin}))
                self.assertEqual(status, 200)
                self.assertIn("stamp stamp-buy", page)


class FormToken(GuardTestCase):

    REFUSED = ('<div class="banner banner-error">This page was out of date, so '
               'nothing was analyzed. Fill in the form below and try '
               'again.</div>')

    def test_form_carries_the_token(self):
        _, page = self.page(self.client.get("/"))
        found = re.search(r'name="form_token" value="([^"]+)"', page)
        self.assertEqual(found.group(1), dealscout.FORM_TOKEN)
        self.assertGreaterEqual(len(dealscout.FORM_TOKEN), 40)

    def test_result_page_form_carries_it_too(self):
        _, page = self.page(self.client.post("/analyze", data=FORM))
        self.assertIn(f'name="form_token" value="{dealscout.FORM_TOKEN}"', page)

    def test_missing_token_is_refused(self):
        # The plain client adds no token; the base address gets past Host.
        status, page = self.page(dealscout.app.test_client().post(
            "/analyze", data=FORM, base_url=BASE_URL))
        self.assertEqual(status, 403)
        self.assertIn(self.REFUSED, page)
        self.assertEqual(database.get_history(), [])

    def test_wrong_token_is_refused(self):
        for token in ("", "wrong", dealscout.FORM_TOKEN[:-1],
                      dealscout.FORM_TOKEN + "x", "jeton-é"):
            with self.subTest(token=token):
                status, page = self.page(self.client.post(
                    "/analyze", data={**FORM, "form_token": token}))
                self.assertEqual(status, 403)
                self.assertIn(self.REFUSED, page)
                # The refusal shows a fresh form to try again with.
                self.assertIn(f'value="{dealscout.FORM_TOKEN}"', page)
        self.assertEqual(database.get_history(), [])

    def test_token_changes_on_each_start(self):
        code = "import dealscout; print(dealscout.FORM_TOKEN)"
        first, second = run_fresh_python(code), run_fresh_python(code)
        self.assertNotEqual(first.strip(), second.strip())


class RealServer(GuardTestCase):
    """The real Werkzeug server on a port picked by the system, so the port
    in the check and in the line is the one it really listens on."""

    def setUp(self):
        super().setUp()
        self.server = make_server("127.0.0.1", 0, dealscout.app, threaded=True)
        self.port = self.server.server_port
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.port}"

    def test_full_round_trip_on_the_real_port(self):
        home = requests.get(self.base + "/", timeout=5)
        self.assertEqual(home.status_code, 200)
        token = re.search(r'name="form_token" value="([^"]+)"', home.text).group(1)
        result = requests.post(self.base + "/analyze",
                               data={**FORM, "form_token": token},
                               headers={"Origin": self.base}, timeout=10)
        self.assertEqual(result.status_code, 200)
        self.assertIn("stamp stamp-buy", result.text)

    def test_wrong_host_names_the_real_port(self):
        response = requests.get(self.base + "/", timeout=5,
                                headers={"Host": "deals.example"})
        self.assertEqual(response.status_code, 400)
        self.assertIn(wrong_host_line(self.port), html.unescape(response.text))

    def test_post_from_another_site_is_refused(self):
        token = re.search(r'name="form_token" value="([^"]+)"',
                          requests.get(self.base + "/", timeout=5).text).group(1)
        response = requests.post(self.base + "/analyze",
                                 data={**FORM, "form_token": token},
                                 headers={"Origin": "https://shop.example"},
                                 timeout=5)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(database.get_history(), [])


if __name__ == "__main__":
    unittest.main()
