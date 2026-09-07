#!/usr/bin/env python3
"""Per-job model broker: AF_UNIX HTTP/1.1 -> fixed host Ollama.

Stdlib only. No CONNECT, no /api/* management, no client-chosen upstream.
"""
from __future__ import annotations
import argparse, json, os, socket, sys, threading, time

ALLOWED_GET = frozenset({"/v1/models"})
ALLOWED_POST = frozenset({"/v1/messages"})
MAX_BODY = int(os.environ.get("BROKER_MAX_BODY", "2097152"))
MAX_HEADER = 16384
UPSTREAM_TIMEOUT = float(os.environ.get("BROKER_UPSTREAM_TIMEOUT", "120"))
CONCURRENCY = int(os.environ.get("BROKER_CONCURRENCY", "2"))
_sem = threading.BoundedSemaphore(CONCURRENCY)


class Reject(Exception):
    def __init__(self, code, msg):
        self.code = code
        self.msg = msg


def _norm_path(raw: str) -> str:
    if not raw or any(ord(c) < 32 for c in raw) or "\\" in raw:
        raise Reject(400, "bad path")
    if "://" in raw or raw.startswith("//") or not raw.startswith("/"):
        raise Reject(400, "absolute or ambiguous path")
    path = raw.split("?", 1)[0]
    if ".." in path or "//" in path or "%" in path:
        raise Reject(400, "encoded or traversal path")
    return path


def _read_headers(sock: socket.socket) -> tuple[bytes, bytes]:
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
        if len(buf) > MAX_HEADER:
            raise Reject(431, "headers too large")
    if b"\r\n\r\n" not in buf:
        raise Reject(400, "incomplete headers")
    head, rest = buf.split(b"\r\n\r\n", 1)
    return head, rest


def _parse_request(head: bytes):
    lines = head.split(b"\r\n")
    if not lines:
        raise Reject(400, "empty")
    parts = lines[0].decode("latin1", "replace").split()
    if len(parts) != 3:
        raise Reject(400, "bad request line")
    method, raw_path, proto = parts[0].upper(), parts[1], parts[2].upper()
    if proto not in {"HTTP/1.0", "HTTP/1.1"}:
        raise Reject(505, "version")
    if method == "CONNECT":
        raise Reject(405, "CONNECT forbidden")
    headers = []
    seen_cl = None
    for line in lines[1:]:
        if b":" not in line:
            raise Reject(400, "bad header")
        name, val = line.split(b":", 1)
        n = name.decode("latin1", "replace").strip().lower()
        v = val.decode("latin1", "replace").strip()
        if n == "transfer-encoding":
            raise Reject(400, "transfer-encoding forbidden")
        if n == "upgrade":
            raise Reject(400, "upgrade forbidden")
        if n == "content-length":
            if seen_cl is not None:
                raise Reject(400, "duplicate content-length")
            try:
                seen_cl = int(v)
            except ValueError:
                raise Reject(400, "bad content-length")
            if seen_cl < 0 or seen_cl > MAX_BODY:
                raise Reject(413, "body too large")
        headers.append((n, v))
    path = _norm_path(raw_path)
    return method, path, proto, headers, seen_cl


def _read_body(sock: socket.socket, already: bytes, length: int | None) -> bytes:
    if length is None:
        return b""
    body = already
    while len(body) < length:
        chunk = sock.recv(min(65536, length - len(body)))
        if not chunk:
            raise Reject(400, "short body")
        body += chunk
    return body[:length]


def _reply(sock: socket.socket, code: int, msg: str, body: bytes = b""):
    reason = {400: "Bad Request", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
              411: "Length Required", 413: "Payload Too Large", 429: "Too Many Requests",
              431: "Headers Too Large", 503: "Service Unavailable",
              505: "HTTP Version Not Supported"}.get(code, "Error")
    if not body:
        body = msg.encode()
    hdr = (
        f"HTTP/1.1 {code} {reason}\r\n"
        f"Content-Type: text/plain\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    try:
        sock.sendall(hdr + body)
    except Exception:
        pass


def _forward(upstream_host: str, upstream_port: int, method: str, path: str,
             body: bytes, bound_model: str, client: socket.socket) -> None:
    if method == "POST" and path == "/v1/messages" and body:
        try:
            doc = json.loads(body.decode("utf-8"))
        except Exception:
            raise Reject(400, "invalid json")
        if not isinstance(doc, dict):
            raise Reject(400, "invalid json object")
        if bound_model:
            doc["model"] = bound_model
        mt = doc.get("max_tokens")
        if isinstance(mt, int) and mt > 8192:
            doc["max_tokens"] = 8192
        body = json.dumps(doc).encode("utf-8")
    up = socket.create_connection((upstream_host, upstream_port), UPSTREAM_TIMEOUT)
    try:
        req = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{upstream_port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"x-api-key: ollama\r\n"
            f"anthropic-version: 2023-06-01\r\n\r\n"
        ).encode() + body
        up.sendall(req)
        while True:
            chunk = up.recv(65536)
            if not chunk:
                break
            client.sendall(chunk)
    finally:
        try:
            up.close()
        except Exception:
            pass


def handle(conn: socket.socket, upstream: tuple[str, int], bound_model: str, log) -> None:
    try:
        head, rest = _read_headers(conn)
        method, path, _proto, headers, clen = _parse_request(head)
        if method == "GET":
            if path not in ALLOWED_GET:
                raise Reject(404, "route")
            if clen:
                raise Reject(400, "get with body")
            body = b""
        elif method == "POST":
            if path not in ALLOWED_POST:
                raise Reject(404, "route")
            if clen is None:
                raise Reject(411, "length required")
            body = _read_body(conn, rest, clen)
        else:
            raise Reject(405, "method")
        if not _sem.acquire(blocking=False):
            raise Reject(429, "busy")
        try:
            log("ok", method, path, len(body))
            _forward(upstream[0], upstream[1], method, path, body, bound_model, conn)
        finally:
            _sem.release()
    except Reject as e:
        log("reject", e.code, e.msg)
        _reply(conn, e.code, e.msg)
    except Exception as e:
        log("err", type(e).__name__)
        _reply(conn, 503, "upstream")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def serve(sock_path: str, upstream: str, bound_model: str) -> None:
    host, _, port_s = upstream.partition(":")
    port = int(port_s or "11434")
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    os.makedirs(os.path.dirname(sock_path) or ".", exist_ok=True)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    os.chmod(sock_path, 0o660)
    srv.listen(16)
    ready = os.path.join(os.path.dirname(sock_path), "ready")
    with open(ready, "w", encoding="utf-8") as f:
        f.write("ok\n")
    os.chmod(ready, 0o644)

    def log(*parts):
        print(time.strftime("%H:%M:%S"), *parts, file=sys.stderr, flush=True)

    log("listen", sock_path, "upstream", f"{host}:{port}", "model", bound_model or "-")
    while True:
        conn, _ = srv.accept()
        threading.Thread(
            target=handle, args=(conn, (host, port), bound_model, log), daemon=True
        ).start()


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sock", default=os.environ.get("MODEL_SOCK", "/bridge/model.sock"))
    p.add_argument("--upstream", default=os.environ.get("OLLAMA_UPSTREAM", "host.docker.internal:11434"))
    p.add_argument("--model", default=os.environ.get("BOUND_MODEL", ""))
    a = p.parse_args(argv)
    serve(a.sock, a.upstream, a.model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
