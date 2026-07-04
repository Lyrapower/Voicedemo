"""Test auth: 401 without token, 401 invalid token."""
import pytest


def test_chat_without_auth_returns_401(client):
    r = client.post("/chat", json={"prompt": "hi"})
    assert r.status_code == 401


def test_chat_with_invalid_token_returns_401(client):
    r = client.post(
        "/chat",
        json={"prompt": "hi"},
        headers={"Authorization": "Bearer invalid-token-xyz"},
    )
    assert r.status_code == 401
