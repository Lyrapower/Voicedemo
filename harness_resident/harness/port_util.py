"""Loopback port helpers — fail fast before bind."""
from __future__ import annotations

import socket


def port_bindable(host: str, port: int) -> bool:
    """Return True if host:port can be bound (not in use)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def assert_port_free(host: str, port: int, *, service: str) -> None:
    if port_bindable(host, port):
        return
    raise RuntimeError(
        f"{service} cannot bind {host}:{port} — port already in use "
        f"(check: lsof -nP -iTCP:{port} -sTCP:LISTEN)"
    )
