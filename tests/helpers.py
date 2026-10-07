"""Helpers shared by the test modules."""

import html
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import BLOCK_NETWORK_CODE, REPO_DIR, TMP_DIR

from flask.testing import FlaskClient

import settings

# Flask's test client sends Host "localhost" with no port, which the tool
# refuses. Tests talk to it at the address a browser would use.
BASE_URL = f"http://localhost:{settings.PORT}"


class LocalClient(FlaskClient):
    """A test client that reaches the tool the way its own page does: at
    BASE_URL, with the form token on every form POST unless the test gives
    its own."""

    def open(self, *args, **kwargs):
        if not args or isinstance(args[0], str):
            kwargs.setdefault("base_url", BASE_URL)
            data = kwargs.get("data")
            if kwargs.get("method") == "POST" and (
                    data is None or isinstance(data, dict)):
                import dealscout
                kwargs["data"] = {"form_token": dealscout.FORM_TOKEN,
                                  **(data or {})}
        return super().open(*args, **kwargs)


def local_client():
    import dealscout
    return LocalClient(dealscout.app, dealscout.app.response_class,
                       use_cookies=True)


def fresh_db():
    """Point the app at a new empty database for one test.
    Returns the patcher; call .stop() or use it as a context manager."""
    path = Path(tempfile.mkdtemp(dir=TMP_DIR)) / "deal_scout.db"
    patcher = mock.patch.dict(os.environ, {"DEALSCOUT_DB_PATH": str(path)})
    patcher.start()
    import database
    database.init_db()
    return patcher, path


def run_fresh_python(code, env_updates=None, cwd=None):
    """Run code in a new interpreter with the repo importable, the network
    blocked and only the given DEALSCOUT_ settings (temp paths for any left
    out). Returns stdout."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("DEALSCOUT_", "EBAY_", "GEMINI_"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(env_updates or {})
    # A path left out would fall back to the real history, photos or .env.
    env.setdefault("DEALSCOUT_ENV_FILE", str(TMP_DIR / "empty.env"))
    env.setdefault("DEALSCOUT_DB_PATH", str(TMP_DIR / "fresh-python.db"))
    env.setdefault("DEALSCOUT_UPLOADS_DIR", str(TMP_DIR / "uploads"))
    result = subprocess.run(
        [sys.executable, "-c", BLOCK_NETWORK_CODE
         + f"import sys; sys.path.insert(0, {str(REPO_DIR)!r})\n" + code],
        cwd=cwd or TMP_DIR, env=env, capture_output=True, text=True,
        timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"subprocess failed:\n{result.stderr}")
    return result.stdout


class RealModeTest(unittest.TestCase):
    """Real mode with fake keys against tests/fake_server.py, on a temp
    database, with every log record (urllib3 included) captured."""

    def setUp(self):
        from tests.fake_server import fake_services
        db_patcher, self.db_path = fresh_db()
        self.addCleanup(db_patcher.stop)
        services = fake_services()
        self.server = services.__enter__()
        self.addCleanup(services.__exit__, None, None, None)
        self.log_lines = []
        handler = _ListHandler(self.log_lines)
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, old_level)
        self.client = local_client()

    def analyze(self, **form):
        """Post the form and return the status and the page as plain text."""
        form.setdefault("title", "Bose SoundLink Flex Bluetooth speaker")
        form.setdefault("asking_price", "35")
        form.setdefault("size_class", "small")
        response = self.client.post("/analyze", data=form)
        return response.status_code, html.unescape(response.get_data(as_text=True))

    def history_page(self):
        return html.unescape(self.client.get("/history").get_data(as_text=True))

    def saved_rows(self):
        import database
        return database.get_history()

    def db_bytes(self):
        return Path(self.db_path).read_bytes()

    def log_text(self):
        return "\n".join(self.log_lines)

    def gemini_calls(self):
        return [r for r in self.server.calls_to("generativelanguage.googleapis.com")
                if r["path"].endswith(":generateContent")]


class _ListHandler(logging.Handler):

    def __init__(self, lines):
        super().__init__(logging.DEBUG)
        self.lines = lines

    def emit(self, record):
        self.lines.append(f"{record.name} {record.levelname} {record.getMessage()}")
        if record.exc_info:
            import traceback
            self.lines.append("".join(traceback.format_exception(*record.exc_info)))
