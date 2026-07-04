#!/usr/bin/env python3
"""Wait for Grid gateway /health — bounded poll, never hangs, does not auto-start."""
from __future__ import annotations

import json
import socket
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8501"
DEFAULT_TIMEOUT_S = 30.0
POLL_INTERVAL_S = 0.5


def port_is_listening(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def gateway_health(base: str = DEFAULT_BASE, *, request_timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"{base.rstrip('/')}/health", timeout=request_timeout) as resp:
            data = json.loads(resp.read().decode())
        return data if data.get("status") == "ok" else None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None


def ensure_gateway_up(
    base: str = DEFAULT_BASE,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Poll /health until ok or *timeout* seconds. Raises SystemExit on failure."""
    base = base.rstrip("/")
    host = "127.0.0.1"
    port = 8501
    if base.startswith("http://"):
        rest = base[len("http://"):]
        if ":" in rest:
            host, port_s = rest.split(":", 1)
            port = int(port_s.split("/")[0])

    deadline = time.monotonic() + timeout
    last_hint = "connection refused"
    while time.monotonic() < deadline:
        health = gateway_health(base)
        if health:
            return health
        if port_is_listening(host, port):
            last_hint = "port open but /health not ok (gateway starting or wedged?)"
        else:
            last_hint = "connection refused (gateway not listening)"
        time.sleep(POLL_INTERVAL_S)

    lines = [
        f"FAIL: gateway not ready at {base}/health after {timeout:.0f}s",
        f"  last: {last_hint}",
    ]
    if port_is_listening(host, port):
        lines.append(f"  port {port} is in use — another process may hold it (not a healthy gateway)")
        lines.append(f"  check: lsof -i :{port}")
        lines.append("  fix: bash scripts/start_grid_gateway.sh  # kills stale listener, foreground start")
    else:
        lines.append("  start: cd grid-sovereign-runtime && python3 gateway/local_gateway.py")
        lines.append("  or:    bash scripts/start_grid_gateway.sh")
    raise SystemExit("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Wait for gateway /health (max 30s default)")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = ap.parse_args(argv)
    health = ensure_gateway_up(args.base, timeout=args.timeout)
    print(json.dumps(health, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
