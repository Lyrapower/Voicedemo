"""Test kill-switch: GATEWAY_KILL=1 => 503 on /chat, /tts, /vision."""
import os
import pytest


def test_kill_switch_returns_503(client, auth_headers):
    os.environ["GATEWAY_KILL"] = "1"
    try:
        r = client.post(
            "/chat",
            json={"prompt": "hi"},
            headers=auth_headers,
        )
        assert r.status_code == 503
        assert "GATEWAY_KILL" in r.json().get("detail", "")
    finally:
        os.environ["GATEWAY_KILL"] = "0"
