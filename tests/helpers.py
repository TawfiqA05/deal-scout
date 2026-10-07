"""Helpers shared by the test modules."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from tests import BLOCK_NETWORK_CODE, REPO_DIR, TMP_DIR


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
    blocked and only the given DEALSCOUT_ settings. Returns stdout."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("DEALSCOUT_", "EBAY_", "GEMINI_"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(env_updates or {})
    result = subprocess.run(
        [sys.executable, "-c", BLOCK_NETWORK_CODE
         + f"import sys; sys.path.insert(0, {str(REPO_DIR)!r})\n" + code],
        cwd=cwd or TMP_DIR, env=env, capture_output=True, text=True,
        timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"subprocess failed:\n{result.stderr}")
    return result.stdout
