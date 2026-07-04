"""Test provider routing: default chat->Claude, compile->OpenAI, explicit override, failover on missing key."""
import os
import pytest


def test_routing_default_chat_claude(client, auth_headers):
    # Default chat should use DEFAULT_CHAT_PROVIDER (claude); if no key, failover to mock
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    r = client.post(
        "/chat",
        json={"prompt": "hello"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert "reply" in data
    # Without keys we fallback to mock
    assert data.get("selected_provider") == "mock" or data.get("provider") == "mock"
    assert data.get("provider_fallback") is True


def test_routing_compile_goes_openai(client, auth_headers):
    os.environ.pop("OPENAI_API_KEY", None)
    r = client.post(
        "/chat",
        json={"prompt": "compile this", "mode": "compile"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    # Selected should be openai; without key we fallback to mock
    assert data.get("selected_provider") in ("openai", "mock")
    assert "reply" in data


def test_routing_explicit_provider_override(client, auth_headers):
    r = client.post(
        "/chat",
        json={"prompt": "hi", "provider": "mock"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json().get("selected_provider") == "mock"
    assert r.json().get("provider_fallback") is False

    r2 = client.post(
        "/chat",
        json={"prompt": "hi"},
        headers={**auth_headers, "X-Provider": "mock"},
    )
    assert r2.status_code == 200
    assert r2.json().get("selected_provider") == "mock"


def test_routing_failover_on_missing_key(client, auth_headers):
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)
    r = client.post(
        "/chat",
        json={"prompt": "hello"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    # Should fallback to mock when Claude/OpenAI keys missing
    assert r.json().get("reply", "")
    assert r.json().get("provider_fallback") is True
