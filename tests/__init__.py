"""Shared test setup. This runs before any test module imports the app.

It points the database, the uploads folder and the .env file at a temp
folder, drops any real keys from the environment, and blocks real network
calls. Importing dealscout creates the database and loads .env, so all of
this has to happen first.
"""

import atexit
import os
import shutil
import socket
import tempfile
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
TMP_DIR = Path(tempfile.mkdtemp(prefix="dealscout-tests-"))
atexit.register(shutil.rmtree, TMP_DIR, ignore_errors=True)

for _key in list(os.environ):
    if _key.startswith(("DEALSCOUT_", "EBAY_", "GEMINI_")):
        del os.environ[_key]

EMPTY_ENV_FILE = TMP_DIR / "empty.env"
EMPTY_ENV_FILE.write_text("")
os.environ["DEALSCOUT_ENV_FILE"] = str(EMPTY_ENV_FILE)
os.environ["DEALSCOUT_DB_PATH"] = str(TMP_DIR / "deal_scout.db")
os.environ["DEALSCOUT_UPLOADS_DIR"] = str(TMP_DIR / "uploads")


class NetworkBlocked(RuntimeError):
    """Raised on any real network call during tests. It is not an OSError,
    so the app's own error handling can't swallow it."""


def _blocked(*args, **kwargs):
    raise NetworkBlocked("a test tried to make a real network call")


socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked

# The same guard as source code, for tests that start a fresh interpreter.
BLOCK_NETWORK_CODE = (
    "import socket\n"
    "def _blocked(*a, **k): raise RuntimeError('network blocked in test')\n"
    "socket.socket.connect = _blocked\n"
    "socket.socket.connect_ex = _blocked\n"
    "socket.create_connection = _blocked\n"
    "socket.getaddrinfo = _blocked\n"
)
