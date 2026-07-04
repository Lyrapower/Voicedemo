"""Test scope enforcement: /chat needs chat, /tts needs tts, /vision needs vision, /admin/tokens needs admin."""
import sqlite3
import secrets
import pytest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DB_PATH
from app.auth import hash_token


def _make_token(scopes: str):
    raw = secrets.token_urlsafe(48)
    token_id = secrets.token_hex(8)
    token_hash = hash_token(raw)
    import time
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO tokens (token_id, token_hash, scopes, daily_limit, daily_used, enabled, created_at, note)
           VALUES (?, ?, ?, 100, 0, 1, ?, 'test')""",
        (token_id, token_hash, scopes, created),
    )
    conn.commit()
    conn.close()
    return raw


def test_chat_with_chat_scope_ok(client, init_test_db):
    raw = _make_token("chat")
    r = client.post("/chat", json={"prompt": "hi"}, headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200


def test_chat_without_chat_scope_returns_403(client, init_test_db):
    raw = _make_token("tts,vision")
    r = client.post("/chat", json={"prompt": "hi"}, headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 403


def test_admin_tokens_requires_admin_scope(client, init_test_db):
    raw = _make_token("chat,tts,vision")
    r = client.get("/admin/tokens", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 403


def test_admin_tokens_with_admin_scope_ok(client, init_test_db, auth_headers):
    r = client.get("/admin/tokens", headers=auth_headers)
    assert r.status_code == 200
