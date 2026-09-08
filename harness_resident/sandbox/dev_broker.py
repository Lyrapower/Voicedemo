#!/usr/bin/env python3
"""Phase 4 CONNECT broker. Manifest-bound. Stdlib only. TEST fixtures use fake upstream."""
from __future__ import annotations
import ipaddress, json, os, socket, ssl, sys, threading, time
from pathlib import Path

MAX_HEADER = 8192
UPSTREAM_HITS = 0
UPSTREAM_LOCK = threading.Lock()


class Reject(Exception):
    def __init__(self, code, msg):
        self.code, self.msg = code, msg


def load_dev(path: str) -> list[dict]:
    rows = []
    p = Path(path)
    if not p.is_file():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [x.strip() for x in s.strip("|").split("|")]
        if len(cells) < 5 or cells[0] in {"host", "---"}:
            continue
        host, port, proto, approved, lanes = cells[:5]
        if not approved or proto.upper() != "CONNECT":
            continue
        try:
            port_i = int(port)
        except ValueError:
            continue
        rows.append({"host": host.lower(), "port": port_i, "lanes": lanes})
    return rows


def _private(ip: str) -> bool:
    try:
        obj = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return bool(obj.is_private or obj.is_loopback or obj.is_link_local or obj.is_multicast or obj.is_reserved)


def _reply(sock, code, msg):
    body = msg.encode()
    hdr = (
        f"HTTP/1.1 {code} Error\r\nContent-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    try:
        sock.sendall(hdr + body)
    except Exception:
        pass


def _parse_connect(head: bytes):
    lines = head.split(b"\r\n")
    parts = lines[0].decode("latin1", "replace").split()
    if len(parts) != 3:
        raise Reject(400, "bad request line")
    method, target, proto = parts[0].upper(), parts[1], parts[2].upper()
    if method != "CONNECT":
        raise Reject(405, "only CONNECT on dev broker")
    if proto not in {"HTTP/1.0", "HTTP/1.1"}:
        raise Reject(505, "version")
    if "://" in target or "/" in target or "@" in target:
        raise Reject(400, "malformed CONNECT")
    if target.count(":") != 1:
        raise Reject(400, "authority host:port required")
    host, port_s = target.rsplit(":", 1)
    host = host.strip("[]").lower()
    try:
        port = int(port_s)
    except ValueError:
        raise Reject(400, "bad port")
    for line in lines[1:]:
        if b":" not in line:
            continue
        n, v = line.split(b":", 1)
        name = n.decode("latin1").strip().lower()
        if name in {"transfer-encoding", "upgrade"}:
            raise Reject(400, f"{name} forbidden")
    return host, port


def handle(conn, rows, fake_up):
    global UPSTREAM_HITS
    try:
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            if len(buf) > MAX_HEADER:
                raise Reject(431, "headers too large")
        if b"\r\n\r\n" not in buf:
            raise Reject(400, "incomplete")
        head, _ = buf.split(b"\r\n\r\n", 1)
        host, port = _parse_connect(head)
        allow = [r for r in rows if r["host"] == host and r["port"] == port]
        if not allow:
            raise Reject(403, "destination not in DEV manifest")
        if fake_up:
            # TEST: do not dial real net; count would-be forward
            with UPSTREAM_LOCK:
                UPSTREAM_HITS += 1
            _reply(conn, 200, "TEST-CONNECT")
            return
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ips = []
        for info in infos:
            ip = info[4][0]
            if _private(ip):
                raise Reject(403, "private or mixed DNS")
            ips.append(ip)
        if not ips:
            raise Reject(502, "resolve empty")
        pin = ips[0]
        up = socket.create_connection((pin, port), 8)
        conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        conn.setblocking(False)
        up.setblocking(False)
        deadline = time.monotonic() + float(os.environ.get("DEV_CONN_SECONDS", "60"))
        while time.monotonic() < deadline:
            r, w, x = [], [], []
            try:
                import select
                r, _, _ = select.select([conn, up], [], [], 1)
            except Exception:
                break
            if conn in r:
                data = conn.recv(65536)
                if not data:
                    break
                up.sendall(data)
            if up in r:
                data = up.recv(65536)
                if not data:
                    break
                conn.sendall(data)
        try:
            up.close()
        except Exception:
            pass
    except Reject as e:
        _reply(conn, e.code, e.msg)
    except Exception:
        _reply(conn, 503, "dev broker error")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def serve(sock_path: str, manifest: str, *, fake_up: bool = False) -> None:
    if os.environ.get("DEV_FAKE_UPSTREAM") == "1":
        print("BLOCKED_TEST_OVERRIDE DEV_FAKE_UPSTREAM", file=sys.stderr, flush=True)
        raise SystemExit(78)
    rows = load_dev(manifest)
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    os.makedirs(os.path.dirname(sock_path) or ".", exist_ok=True)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    os.chmod(sock_path, 0o660)
    srv.listen(16)
    open(os.path.join(os.path.dirname(sock_path), "dev.ready"), "w").write("ok\n")
    print(time.strftime("%H:%M:%S"), "dev listen", sock_path, "rows", len(rows), file=sys.stderr, flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn, rows, fake_up), daemon=True).start()


if __name__ == "__main__":
    serve(os.environ.get("DEV_SOCK", "/bridge/dev.sock"),
          os.environ.get("DEV_PATH", "/etc/egress/DEV.md"))
