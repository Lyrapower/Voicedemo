#!/usr/bin/env python3
"""Phase-1 model broker HTTP boundary tests (stdlib, no Docker)."""
from __future__ import annotations
import os, socket, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sandbox"))
import model_broker as MB  # noqa: E402


def _http(sock_path: str, raw: bytes, timeout=2.0) -> bytes:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(sock_path)
    s.sendall(raw)
    data = b""
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass
    finally:
        s.close()
    return data


TOKEN = "synth-job-token-not-real"


def _auth() -> bytes:
    return f"x-api-key: {TOKEN}\r\n".encode()


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.sock = str(Path(self.td.name) / "model.sock")
        self.up_host, self.up_port = "127.0.0.1", self._serve_upstream()
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "sandbox" / "model_broker.py"),
             "--sock", self.sock, "--upstream", f"{self.up_host}:{self.up_port}",
             "--model", "glm-5.3:cloud", "--token", TOKEN],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        for _ in range(50):
            if Path(self.td.name, "ready").exists() and Path(self.sock).exists():
                break
            time.sleep(0.05)
        else:
            self.fail("broker did not bind")

    def tearDown(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()
        self.td.cleanup()

    def _serve_upstream(self):
        srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0)); srv.listen(8)
        port = srv.getsockname()[1]
        self._up_hits = []

        def loop():
            while True:
                try:
                    c, _ = srv.accept()
                    self._up_hits.append(time.time())
                except Exception:
                    return
                try:
                    c.recv(65536)
                    body = b'{"id":"m","type":"message","role":"assistant","content":[{"type":"text","text":"pong"}]}'
                    c.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                        + body
                    )
                except Exception:
                    pass
                finally:
                    try: c.close()
                    except Exception: pass
        threading.Thread(target=loop, daemon=True).start()
        self._up = srv
        return port

    def test_connect_rejected(self):
        before = len(self._up_hits)
        raw = b"CONNECT 10.0.0.27:8501 HTTP/1.1\r\nHost: 10.0.0.27:8501\r\n\r\n"
        out = _http(self.sock, raw)
        self.assertTrue(out.startswith(b"HTTP/1.1 405"), out[:80])
        time.sleep(0.05)
        self.assertEqual(len(self._up_hits), before)

    def test_api_pull_rejected(self):
        before = len(self._up_hits)
        raw = b"POST /api/pull HTTP/1.1\r\nHost: x\r\n" + _auth() + b"Content-Length: 2\r\n\r\n{}"
        out = _http(self.sock, raw)
        self.assertTrue(out.startswith(b"HTTP/1.1 404"), out[:80])
        time.sleep(0.05)
        self.assertEqual(len(self._up_hits), before)

    def test_api_delete_create_rejected(self):
        before = len(self._up_hits)
        for path in (b"/api/delete", b"/api/create"):
            raw = b"POST " + path + b" HTTP/1.1\r\nHost: x\r\n" + _auth() + b"Content-Length: 2\r\n\r\n{}"
            out = _http(self.sock, raw)
            self.assertTrue(out.startswith(b"HTTP/1.1 404"), out[:80])
        time.sleep(0.05)
        self.assertEqual(len(self._up_hits), before)

    def test_upgrade_rejected(self):
        raw = b"GET /v1/models HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n\r\n"
        out = _http(self.sock, raw)
        self.assertTrue(out.startswith(b"HTTP/1.1 400"), out[:80])

    def test_transfer_encoding_rejected(self):
        raw = b"POST /v1/messages HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n"
        out = _http(self.sock, raw)
        self.assertTrue(out.startswith(b"HTTP/1.1 400"), out[:80])

    def test_absolute_url_rejected(self):
        raw = b"GET http://evil/v1/models HTTP/1.1\r\nHost: x\r\n\r\n"
        out = _http(self.sock, raw)
        self.assertTrue(out.startswith(b"HTTP/1.1 400"), out[:80])

    def test_messages_ok(self):
        body = b'{"model":"attacker","max_tokens":8,"messages":[{"role":"user","content":"hi"}]}'
        raw = (
            b"POST /v1/messages HTTP/1.1\r\nHost: x\r\n" + _auth()
            + f"Content-Length: {len(body)}\r\n\r\n".encode() + body
        )
        out = _http(self.sock, raw)
        self.assertIn(b"HTTP/1.1 200", out)
        self.assertIn(b"pong", out)

    def test_missing_and_wrong_token_no_upstream(self):
        before = len(self._up_hits)
        body = b'{"model":"x","max_tokens":8,"messages":[{"role":"user","content":"hi"}]}'
        missing = (
            b"POST /v1/messages HTTP/1.1\r\nHost: x\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode() + body
        )
        wrong = (
            b"POST /v1/messages HTTP/1.1\r\nHost: x\r\nx-api-key: ollama\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode() + body
        )
        for raw in (missing, wrong):
            out = _http(self.sock, raw)
            self.assertTrue(out.startswith(b"HTTP/1.1 401"), out[:80])
        time.sleep(0.05)
        self.assertEqual(len(self._up_hits), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
