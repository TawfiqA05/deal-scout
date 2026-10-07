"""A database made with the schema from commit 05cbe3a still opens in History.
Later runs that change the schema have to keep this passing."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import TMP_DIR

import dealscout

SCHEMA_05CBE3A = """
    CREATE TABLE IF NOT EXISTS listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        analyzed_at TEXT NOT NULL,
        source TEXT,
        title TEXT NOT NULL,
        asking_price REAL NOT NULL,
        url TEXT,
        description TEXT,
        category_guess TEXT,
        size_class TEXT,
        verdict TEXT NOT NULL,
        est_resale_low REAL,
        est_resale_high REAL,
        est_profit_low REAL,
        est_profit_high REAL,
        suggested_offer REAL,
        comps_count INTEGER,
        fee_percent REAL,
        shipping_est REAL,
        vision_report TEXT,
        negotiation_draft TEXT,
        notes TEXT
    )
"""


class OldDatabaseOpensInHistory(unittest.TestCase):

    def test_row_saved_with_old_schema_shows_in_history(self):
        path = Path(tempfile.mkdtemp(dir=TMP_DIR)) / "old.db"
        conn = sqlite3.connect(path)
        conn.execute(SCHEMA_05CBE3A)
        conn.execute(
            "INSERT INTO listings (analyzed_at, source, title, asking_price,"
            " category_guess, size_class, verdict, est_resale_low,"
            " est_resale_high, est_profit_low, est_profit_high,"
            " suggested_offer, comps_count, fee_percent, shipping_est,"
            " vision_report, negotiation_draft)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("2026-09-01T10:00:00", "manual", "Bose QuietComfort 35 II", 70.0,
             "electronics", "small", "NEGOTIATE", 110.0, 125.0, 18.5, 31.0,
             58.0, 14, 13.25, 6.0,
             '{"condition": "Ear pads worn", "red_flags": [],'
             ' "missing_info": ["Ask about battery life"]}',
             "Hi, would you take $58?"))
        conn.commit()
        conn.close()

        with mock.patch.dict(os.environ, {"DEALSCOUT_DB_PATH": str(path)}):
            client = dealscout.app.test_client()
            page = client.get("/history").get_data(as_text=True)
            filtered = client.get("/history?verdict=NEGOTIATE").get_data(as_text=True)

        self.assertIn("Bose QuietComfort 35 II", page)
        self.assertIn("Ear pads worn", page)
        self.assertIn("Hi, would you take $58?", page)
        self.assertIn("Bose QuietComfort 35 II", filtered)


if __name__ == "__main__":
    unittest.main()
