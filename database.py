"""
SQLite storage for analysis history, one row per analyzed listing.
The table is created on first run.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent / "deal_scout.db"


def db_path() -> Path:
    """DEALSCOUT_DB_PATH overrides the default file next to the code.
    Read on every call so tests can point it at a temp file."""
    return Path(os.environ.get("DEALSCOUT_DB_PATH") or DEFAULT_DB_PATH)


def _connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the table the first time the tool runs."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analyzed_at TEXT NOT NULL,
                source TEXT,                -- 'ebay_url' or 'manual'
                title TEXT NOT NULL,
                asking_price REAL NOT NULL,
                url TEXT,
                description TEXT,
                category_guess TEXT,
                size_class TEXT,
                verdict TEXT NOT NULL,      -- BUY / NEGOTIATE / PASS
                est_resale_low REAL,
                est_resale_high REAL,
                est_profit_low REAL,
                est_profit_high REAL,
                suggested_offer REAL,
                comps_count INTEGER,
                fee_percent REAL,
                shipping_est REAL,
                vision_report TEXT,         -- JSON: condition, red flags, missing info
                negotiation_draft TEXT,
                notes TEXT
            )
        """)


def save_listing(data: dict) -> int:
    """Save one analyzed listing. Returns its database id."""
    with _connect() as conn:
        cur = conn.execute("""
            INSERT INTO listings (
                analyzed_at, source, title, asking_price, url, description,
                category_guess, size_class, verdict,
                est_resale_low, est_resale_high, est_profit_low, est_profit_high,
                suggested_offer, comps_count, fee_percent, shipping_est,
                vision_report, negotiation_draft, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(timespec="seconds"),
            data.get("source"),
            data.get("title", "(untitled)"),
            data.get("asking_price", 0),
            data.get("url"),
            data.get("description"),
            data.get("category_guess"),
            data.get("size_class"),
            data.get("verdict", "PASS"),
            data.get("est_resale_low"),
            data.get("est_resale_high"),
            data.get("est_profit_low"),
            data.get("est_profit_high"),
            data.get("suggested_offer"),
            data.get("comps_count"),
            data.get("fee_percent"),
            data.get("shipping_est"),
            json.dumps(data.get("vision_report") or {}),
            data.get("negotiation_draft"),
            data.get("notes"),
        ))
        return cur.lastrowid


def recent_duplicate(title: str, asking_price: float):
    """Return a recent identical listing if you've already scored it
    (same title and price in the last 14 days), else None."""
    with _connect() as conn:
        row = conn.execute("""
            SELECT * FROM listings
            WHERE title = ? AND asking_price = ?
              AND analyzed_at >= datetime('now', '-14 days')
            ORDER BY analyzed_at DESC LIMIT 1
        """, (title, asking_price)).fetchone()
        return dict(row) if row else None


def get_history(verdict_filter: str | None = None, limit: int = 200):
    """All past analyses, newest first. Optionally only BUY/NEGOTIATE/PASS."""
    with _connect() as conn:
        if verdict_filter in ("BUY", "NEGOTIATE", "PASS"):
            rows = conn.execute(
                "SELECT * FROM listings WHERE verdict = ? "
                "ORDER BY analyzed_at DESC LIMIT ?",
                (verdict_filter, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM listings ORDER BY analyzed_at DESC LIMIT ?",
                (limit,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["vision_report"] = json.loads(d.get("vision_report") or "{}")
            except json.JSONDecodeError:
                d["vision_report"] = {}
            result.append(d)
        return result
