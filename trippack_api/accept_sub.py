#!/usr/bin/env python3
"""Lightweight smoke checks for TripPackAI backend (optional)."""
import os
import sys

import httpx

BASE = os.environ.get("TRIPPACK_BASE", "http://127.0.0.1:8810")


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=20.0)
    r = c.get("/")
    print(f"GET / {r.status_code}")
    assert r.status_code == 200
    assert "TripPackAI Backend" in r.text

    r = c.get("/health")
    print(f"GET /health {r.status_code} {r.json()}")
    assert r.json().get("ok") is True

    r = c.get("/provider-status")
    print(f"GET /provider-status {r.status_code} {r.json()}")
    assert "provider_mode" in r.json()

    r = c.get("/trip-goals")
    print(f"GET /trip-goals {r.status_code}")
    assert r.status_code == 200
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(e, file=sys.stderr)
        raise SystemExit(1)
