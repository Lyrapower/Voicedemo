#!/usr/bin/env python3
"""Supervisor-owned isolation in the live cc netns. Writes /work/isolation_receipt.json.

127.0.0.1:11434 OPEN is the model_relay in this netns, not host Ollama.
Protocol probes distinguish relay-with-auth from unauthorized model access.
"""
from __future__ import annotations
import json, os, socket, time, urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def try_connect(host, port, timeout=2.0):
    try:
        s = socket.create_connection((host, port), timeout)
        s.close()
        return {"result": "OPEN", "error": None}
    except Exception as e:
        return {"result": type(e).__name__, "error": str(e)[:160]}

def http_raw(host, port, raw, timeout=2.0):
    s = socket.create_connection((host, port), timeout)
    try:
        s.sendall(raw)
        s.settimeout(timeout)
        out = b""
        while True:
            try:
                chunk = s.recv(800)
            except socket.timeout:
                break
            if not chunk:
                break
            out += chunk
            if len(out) >= 800:
                break
        return out
    finally:
        try:
            s.close()
        except Exception:
            pass

def loopback_http():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ISOOK")
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 18765), H)
    t = Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        with urllib.request.urlopen("http://127.0.0.1:18765/", timeout=2) as r:
            body = r.read().decode()
            code = r.status
    finally:
        srv.shutdown()
    return {"port": 18765, "status": code, "body": body, "published_host": False}

def mount_flags():
    text = open("/proc/self/mountinfo", encoding="utf-8", errors="replace").read()
    hits = []
    for needle in ("docker.sock", "/Users/", "/var/run/docker", "diary.db", "cloud_memory"):
        if needle in text:
            hits.append(needle)
    return {"mountinfo_hits": hits, "has_docker_sock": "docker.sock" in text}

def broker_rejects():
    cases = []
    for raw, label in (
        (b'{"action":"fetch","url":"https://example.com","lane":"research"}', "forge_lane"),
        (b'{"action":"fetch","url":"https://example.com","opener":true}', "opener"),
        (b'{"action":"shell","cmd":"id"}', "unknown_action"),
    ):
        req = (
            b"POST /action HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            + f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw
        )
        try:
            s = socket.create_connection(("127.0.0.1", 3128), 2)
            s.sendall(req)
            out = s.recv(800)
            s.close()
            cases.append({"label": label, "prefix": out[:80].decode("latin1", "replace"), "ok": out.startswith(b"HTTP/1.1 4")})
        except Exception as e:
            cases.append({"label": label, "error": type(e).__name__, "ok": False})
    return cases

def extra_ifaces():
    extra = []
    if os.path.exists("/proc/net/route"):
        for i, line in enumerate(open("/proc/net/route", encoding="ascii")):
            if i == 0:
                continue
            cols = line.split()
            if cols and cols[0] not in {"lo", "lo0"}:
                extra.append(cols[0])
    return sorted(set(extra))

def _listener_11434():
    """Identify who owns 127.0.0.1:11434 via /proc. No package install."""
    path = "/proc/net/tcp"
    if not os.path.exists(path):
        return {"ok": False, "reason": "no /proc/net/tcp"}
    target = "0100007F:2CA6"
    inode = None
    with open(path, encoding="ascii") as f:
        for i, line in enumerate(f):
            if i == 0:
                continue
            cols = line.split()
            if len(cols) < 10:
                continue
            if cols[1].upper() == target and cols[3] == "0A":
                inode = cols[9]
                break
    if not inode:
        return {"ok": False, "reason": "no listening 127.0.0.1:11434"}
    exe = None
    pid = None
    for ent in os.listdir("/proc"):
        if not ent.isdigit():
            continue
        fd_dir = f"/proc/{ent}/fd"
        try:
            for fd in os.listdir(fd_dir):
                try:
                    tgt = os.readlink(os.path.join(fd_dir, fd))
                except OSError:
                    continue
                if tgt == f"socket:[{inode}]":
                    pid = int(ent)
                    try:
                        exe = os.readlink(f"/proc/{ent}/exe")
                    except OSError:
                        exe = None
                    break
        except OSError:
            continue
        if pid is not None:
            break
    cmdline = ""
    if pid is not None:
        try:
            cmdline = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\x00", b" ").decode("latin1", "replace")[:200]
        except OSError:
            pass
    return {"ok": True, "inode": inode, "pid": pid, "exe": exe, "cmdline": cmdline}

def model_protocol_probes():
    """TCP OPEN on 11434 is the relay. Unauthorized generate must not succeed."""
    out = {"loopback_tcp": try_connect("127.0.0.1", 11434), "listener": _listener_11434(), "http": []}
    noauth_get = b"GET /v1/models HTTP/1.1\r\nHost: 127.0.0.1:11434\r\n\r\n"
    noauth_post = (
        b"POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1:11434\r\n"
        b"Content-Type: application/json\r\nContent-Length: 51\r\n\r\n"
        b'{"model":"x","max_tokens":8,"messages":[{"role":"user","content":"ping"}]}'
    )
    for label, raw in (("noauth_models", noauth_get), ("noauth_messages", noauth_post)):
        try:
            body = http_raw("127.0.0.1", 11434, raw)
            prefix = body[:80].decode("latin1", "replace")
            out["http"].append({
                "label": label,
                "http_prefix": prefix,
                "unauthorized_rejected": body.startswith(b"HTTP/1.1 401") or body.startswith(b"HTTP/1.1 403"),
                "got_generation": b'"role":"assistant"' in body or b'"content"' in body and b"pong" in body,
            })
        except Exception as e:
            out["http"].append({"label": label, "error": type(e).__name__, "unauthorized_rejected": False})
    tok = os.environ.get("ANTHROPIC_AUTH_TOKEN") or ""
    if tok:
        body = json.dumps({"model": "x", "max_tokens": 8, "messages": [{"role": "user", "content": "ping"}]}).encode()
        raw = (
            b"POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1:11434\r\n"
            + f"x-api-key: {tok}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        try:
            resp = http_raw("127.0.0.1", 11434, raw, timeout=8.0)
            prefix = resp[:24].decode("latin1", "replace")
            out["http"].append({
                "label": "job_token_messages",
                "http_prefix": prefix,
                "authorized_attempt": True,
                "upstream_ok": resp.startswith(b"HTTP/1.1 200"),
            })
        except Exception as e:
            out["http"].append({"label": "job_token_messages", "error": type(e).__name__, "authorized_attempt": True})
    return out

def main():
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"
    rec = {
        "executor": "supervisor_in_job_diag",
        "ts": utc(),
        "container_hostname": socket.gethostname(),
        "loopback": None,
        "host_probes": [],
        "model_relay": None,
        "mounts": mount_flags(),
        "broker_rejects": [],
        "extra_if": extra_ifaces(),
        "proxies_cleared": True,
        "note": "127.0.0.1:11434 in this netns is model_relay->unix broker, not host Ollama",
    }
    try:
        rec["loopback"] = loopback_http()
    except Exception as e:
        rec["loopback"] = {"error": type(e).__name__, "detail": str(e)[:160]}
    try:
        rec["model_relay"] = model_protocol_probes()
    except Exception as e:
        rec["model_relay"] = {"error": type(e).__name__, "detail": str(e)[:160]}
    extra_targets = ["host.docker.internal:11434"]
    gw = None
    if os.path.exists("/proc/net/route"):
        with open("/proc/net/route", encoding="ascii") as f:
            for i, line in enumerate(f):
                if i == 0:
                    continue
                cols = line.split()
                if cols and cols[1] == "00000000":
                    raw = int(cols[2], 16)
                    gw = f"{raw & 255}.{(raw >> 8) & 255}.{(raw >> 16) & 255}.{(raw >> 24) & 255}:11434"
                    break
    if gw:
        extra_targets.append(gw)
    seen = set()
    for item in [t for t in os.environ.get("ISOLATE_TARGETS", "").split(",") if t.strip()] + extra_targets:
        if item in seen:
            continue
        seen.add(item)
        host, port_s = item.rsplit(":", 1)
        rec["host_probes"].append({"target": item, "host": host.strip("[]"), "port": int(port_s), **try_connect(host.strip("[]"), int(port_s))})
    rec["broker_rejects"] = broker_rejects()
    open("/work/isolation_receipt.json", "w", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False, indent=2))
    open("/work/isolation_receipt.log", "w", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
