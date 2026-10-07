"""Tests never touch real history, real photos, the real .env or the network."""

import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import EMPTY_ENV_FILE, TMP_DIR, NetworkBlocked
from tests.helpers import run_fresh_python

import database
import dealscout


class PathsComeFromEnvironment(unittest.TestCase):

    def test_suite_uses_temp_paths(self):
        self.assertEqual(Path(dealscout.ENV_FILE), EMPTY_ENV_FILE)
        self.assertTrue(Path(dealscout.UPLOAD_DIR).is_relative_to(TMP_DIR))
        self.assertTrue(database.db_path().is_relative_to(TMP_DIR))

    def test_database_path_setting_is_used(self):
        target = Path(tempfile.mkdtemp(dir=TMP_DIR)) / "history.db"
        with mock.patch.dict(os.environ, {"DEALSCOUT_DB_PATH": str(target)}):
            database.init_db()
            row_id = database.save_listing({"title": "Test lamp",
                                            "asking_price": 20.0})
            self.assertTrue(target.exists())
            self.assertEqual(database.get_history()[0]["id"], row_id)

    def test_uploads_setting_is_used_on_import(self):
        target = TMP_DIR / "uploads-from-env"
        out = run_fresh_python(
            "import dealscout; print(dealscout.UPLOAD_DIR)",
            {"DEALSCOUT_ENV_FILE": str(EMPTY_ENV_FILE),
             "DEALSCOUT_DB_PATH": str(TMP_DIR / "import.db"),
             "DEALSCOUT_UPLOADS_DIR": str(target)})
        self.assertEqual(out.strip(), str(target))
        self.assertTrue(target.is_dir())

    def test_env_file_setting_is_used(self):
        env_file = TMP_DIR / "marker.env"
        env_file.write_text("DEALSCOUT_TEST_MARKER=loaded\n")
        out = run_fresh_python(
            "import os, dealscout; print(os.environ.get('DEALSCOUT_TEST_MARKER'))",
            {"DEALSCOUT_ENV_FILE": str(env_file),
             "DEALSCOUT_DB_PATH": str(TMP_DIR / "import.db"),
             "DEALSCOUT_UPLOADS_DIR": str(TMP_DIR / "uploads")})
        self.assertEqual(out.strip(), "loaded")

    def test_settings_are_named_in_env_example(self):
        example = (Path(dealscout.APP_DIR) / ".env.example").read_text()
        for name in ("DEALSCOUT_DB_PATH", "DEALSCOUT_UPLOADS_DIR",
                     "DEALSCOUT_ENV_FILE"):
            self.assertIn(name, example)
        env_file_lines = [line for line in example.splitlines()
                          if "DEALSCOUT_ENV_FILE" in line]
        self.assertTrue(all(line.lstrip().startswith("#")
                            for line in env_file_lines))


class NetworkIsBlocked(unittest.TestCase):

    def test_socket_connect_is_blocked(self):
        with self.assertRaises(NetworkBlocked):
            socket.create_connection(("example.com", 80))

    def test_requests_is_blocked(self):
        import requests
        with self.assertRaises(NetworkBlocked):
            requests.get("https://example.com", timeout=1)


if __name__ == "__main__":
    unittest.main()
