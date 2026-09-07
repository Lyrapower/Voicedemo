#!/usr/bin/env python3
"""11434 host-rewrite + CONNECT whitelist (EGRESS.md 拍板, :443)."""
from __future__ import annotations
import os, re, socket, threading, time
from pathlib import Path

EGRESS = Path(os.environ.get("EGRESS_PATH", "/etc/egress/EGRESS.md"))
DENIED = Path(os.environ.get("DENIED_PATH", "/var/log/egress_denied.jsonl"))
PROXY = int(os.environ.get("PROXY_PORT", "3128"))
OLLAMA = int(os.environ.get("OLLAMA_PORT", "11434"))
UP = os.environ.get("OLLAMA_UP", "host.docker.internal")


def approved() -> set[str]:
    rows: set[str] = set()
    if not EGRESS.exists():
        return rows
    for line in EGRESS.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---") or "domain" in line[:12]:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8:
            continue
        domain, _p, ro, _a, _r, _g, stamp, _l = cells[:8]
        if stamp and ro.lower() == "yes" and not domain.startswith("*"):
            rows.add(domain.lower())
    return rows


def deny(host: str, reason: str) -> None:
    DENIED.parent.mkdir(parents=True, exist_ok=True)
    with DENIED.open("a", encoding="utf-8") as f:
        f.write('{"ts":%s,"host":"%s","reason":"%s"}\n' % (time.time(), host, reason))


def pipe(a, b):
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except Exception:
        pass
    try:
        b.shutdown(socket.SHUT_WR)
    except Exception:
        pass


def tunnel(a, b):
    threading.Thread(target=pipe, args=(a, b), daemon=True).start()
    pipe(b, a)


def handle_connect(conn: socket.socket) -> None:
    try:
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 8192:
            chunk = conn.recv(1024)
            if not chunk:
                break
            buf += chunk
        parts = buf.split(b"\r\n", 1)[0].decode("latin1", "replace").split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            conn.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
            return
        host, _, port_s = parts[1].partition(":")
        port = int(port_s or "443")
        if port != 443 or host.lower() not in approved():
            deny(host, "not_approved" if port == 443 else "port")
            conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            return
        remote = socket.create_connection((host, port), 20)
        conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        tunnel(conn, remote)
    except Exception:
        try:
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def handle_ollama(conn: socket.socket) -> None:
    try:
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 65536:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
        buf = re.sub(br"(?i)host:\s*[^\r\n]+", b"Host: 127.0.0.1:11434", buf, count=1)
        buf = re.sub(br"(?i)origin:\s*[^\r\n]+", b"Origin: http://127.0.0.1:11434", buf, count=1)
        remote = socket.create_connection((UP, 11434), 20)
        remote.sendall(buf)
        tunnel(conn, remote)
    except Exception:
        try:
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def serve(port: int, handler) -> None:
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port)); srv.listen(32)
    while True:
        c, _ = srv.accept()
        threading.Thread(target=handler, args=(c,), daemon=True).start()


if __name__ == "__main__":
    threading.Thread(target=serve, args=(PROXY, handle_connect), daemon=True).start()
    serve(OLLAMA, handle_ollama)
