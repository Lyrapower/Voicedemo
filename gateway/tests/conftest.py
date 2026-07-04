"""Pytest fixtures: test DB, app client, token."""
import os
import tempfile
from pathlib import Path

import pytest

# Ensure app is importable
ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

# Use a temp DB for tests
@pytest.fixture(scope="session")
def test_db_path():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "test_gateway.db")
    os.environ["GATEWAY_DB_PATH"] = path
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


@pytest.fixture(scope="session")
def init_test_db(test_db_path):
    from scripts.init_db import init_db
    init_db()
    yield


@pytest.fixture
def app(init_test_db):
    os.environ["GATEWAY_KILL"] = "0"
    from app.main import app
    return app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def token_info(init_test_db):
    """Create a token with chat,tts,vision,admin and return (token_id, raw_token)."""
    import sqlite3
    import secrets
    from app.config import DB_PATH
    from app.auth import hash_token
    raw = secrets.token_urlsafe(48)
    token_id = secrets.token_hex(8)
    token_hash = hash_token(raw)
    import time
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO tokens (token_id, token_hash, scopes, daily_limit, daily_used, enabled, created_at, note)
           VALUES (?, ?, ?, 1000, 0, 1, ?, 'test')""",
        (token_id, token_hash, "chat,tts,vision,admin", created),
    )
    conn.commit()
    conn.close()
    return token_id, raw


@pytest.fixture
def auth_headers(token_info):
    _, raw = token_info
    return {"Authorization": f"Bearer {raw}"}
