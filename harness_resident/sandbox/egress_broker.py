#!/usr/bin/env python3
"""JSON action broker: AF_UNIX -> web_fetch_v2. Not CONNECT. Stdlib only."""
from __future__ import annotations
import json, os, socket, sys, threading, time

ALLOWED = {
    "fetch": frozenset({"action", "url", "max_chars"}),
    "search": frozenset({"action", "query", "n", "max_pages"}),
    "search_many": frozenset({"action", "queries", "n", "max_pages"}),
    "fetch_many": frozenset({"action", "urls", "max_chars", "workers"}),
}
FORBIDDEN = {
    "opener", "_private_check", "signal_filter", "_tool", "searxng_url",
    "providers", "lane", "egress_path", "db_path", "route_id", "mission_id",
    "substrate", "job_id",
}
MAX_BODY = int(os.environ.get("EGRESS_MAX_BODY", "65536"))
MAX_HEADER = 8192


class Reject(Exception):
    def __init__(self, code, msg):
        self.code, self.msg = code, msg


def _reply(sock, code, obj):
    body = json.dumps(obj, ensure_ascii=False).encode()
    hdr = (
        f"HTTP/1.1 {code} {'OK' if code==200 else 'Error'}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode()
    try:
        sock.sendall(hdr + body)
    except Exception:
        pass


def _parse(sock):
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
    lines = head.split(b"\r\n")
    parts = lines[0].decode("latin1", "replace").split()
    if len(parts) != 3:
        raise Reject(400, "bad request line")
    method, path, proto = parts[0].upper(), parts[1], parts[2].upper()
    if method == "CONNECT":
        raise Reject(405, "CONNECT forbidden")
    if proto not in {"HTTP/1.0", "HTTP/1.1"}:
        raise Reject(505, "version")
    clen = None
    for line in lines[1:]:
        if b":" not in line:
            raise Reject(400, "bad header")
        n, v = line.split(b":", 1)
        name = n.decode("latin1").strip().lower()
        val = v.decode("latin1").strip()
        if name == "transfer-encoding":
            raise Reject(400, "transfer-encoding forbidden")
        if name == "upgrade":
            raise Reject(400, "upgrade forbidden")
        if name == "content-length":
            if clen is not None:
                raise Reject(400, "duplicate content-length")
            clen = int(val)
            if clen < 0 or clen > MAX_BODY:
                raise Reject(413, "body too large")
    if method != "POST" or path not in {"/", "/action"}:
        raise Reject(404, "route")
    if clen is None:
        raise Reject(411, "length required")
    body = rest
    while len(body) < clen:
        chunk = sock.recv(min(65536, clen - len(body)))
        if not chunk:
            raise Reject(400, "short body")
        body += chunk
    return body[:clen]


def _dispatch(raw: bytes, bound: dict) -> dict:
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception:
        raise Reject(400, "invalid json")
    if not isinstance(doc, dict):
        raise Reject(400, "invalid json object")
    extra = set(doc) - set().union(*ALLOWED.values())
    if extra or (set(doc) & FORBIDDEN):
        raise Reject(400, "unknown or forbidden field")
    action = doc.get("action")
    if action not in ALLOWED:
        raise Reject(404, "unknown action")
    if set(doc) - ALLOWED[action]:
        raise Reject(400, "field not allowed for action")
    sys.path.insert(0, os.environ.get("WEB_FETCH_DIR", "/opt/grid"))
    import web_fetch_v2 as WF
    lane = bound["lane"]
    eg = bound["egress_path"]
    kw = {"egress_path": eg, "mission_id": bound.get("job_id")}
    if action == "fetch":
        if "url" not in doc:
            raise Reject(400, "url required")
        return WF.fetch(str(doc["url"]), lane, max_chars=int(doc.get("max_chars") or WF.MAX_CHARS), **kw)
    if action == "search":
        if "query" not in doc:
            raise Reject(400, "query required")
        return WF.search(str(doc["query"]), lane, n=int(doc.get("n") or 8),
                         max_pages=int(doc.get("max_pages") or 3), **kw)
    if action == "search_many":
        qs = doc.get("queries")
        if not isinstance(qs, list):
            raise Reject(400, "queries must be a list")
        return WF.search_many(qs, lane, n=int(doc.get("n") or 8),
                              max_pages=int(doc.get("max_pages") or 2), **kw)
    urls = doc.get("urls")
    if not isinstance(urls, list):
        raise Reject(400, "urls must be a list")
    return WF.fetch_many(urls, lane, workers=int(doc.get("workers") or 4),
                         max_chars=int(doc.get("max_chars") or WF.MAX_CHARS), **kw)


def handle(conn, bound):
    try:
        raw = _parse(conn)
        out = _dispatch(raw, bound)
        _reply(conn, 200, out)
    except Reject as e:
        _reply(conn, e.code, {"ok": False, "status": "REJECTED", "reason": e.msg})
    except Exception as e:
        _reply(conn, 500, {"ok": False, "status": "BROKER_ERROR", "reason": type(e).__name__})
    finally:
        try:
            conn.close()
        except Exception:
            pass


def serve(sock_path: str, bound: dict) -> None:
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    os.makedirs(os.path.dirname(sock_path) or ".", exist_ok=True)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    os.chmod(sock_path, 0o660)
    srv.listen(16)
    ready = os.path.join(os.path.dirname(sock_path), "egress.ready")
    open(ready, "w").write("ok\n")
    print(time.strftime("%H:%M:%S"), "egress listen", sock_path, "lane", bound["lane"], file=sys.stderr, flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn, bound), daemon=True).start()


if __name__ == "__main__":
    # Never inherit a host/shell GitHub token. Research loader sets the flag in-process.
    os.environ.pop("GITHUB_TOKEN", None)
    os.environ.pop("GRID_GITHUB_RESEARCH_LOADED", None)
    bound = {
        "lane": os.environ.get("BOUND_LANE", "cc"),
        "egress_path": os.environ.get("EGRESS_PATH", "/etc/egress/EGRESS.md"),
        "job_id": os.environ.get("BOUND_JOB_ID", ""),
    }
    token_file = os.environ.get("GITHUB_RESEARCH_TOKEN_FILE", "").strip()
    if bound["lane"] in {"research", "maintainer"} and token_file:
        try:
            from pathlib import Path
            sys.path.insert(0, os.environ.get("WEB_FETCH_DIR", "/opt/grid"))
            from github_research_secret import load_into_environ
            load_into_environ(path=Path(token_file))
        except Exception:
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GRID_GITHUB_RESEARCH_LOADED", None)
    serve(os.environ.get("EGRESS_SOCK", "/bridge/egress.sock"), bound)
