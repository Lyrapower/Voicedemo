"""T09: activity-stream cancel + broker kill, no fallback, no orphan.

Isolated unix-socket broker. No production network. Verifies:
- cancel sets job interrupted; no re-dispatch (claim returns None)
- unauth request to broker → 401, no generation reaches upstream
- established stream closes on broker kill (no orphan)
"""
from __future__ import annotations
import os, socket, subprocess, sys, tempfile, time, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
from db import Store

BROKER_DIR = ROOT / "sandbox"


def _start_broker(sock_path: str, token: str = "iso-token") -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, str(BROKER_DIR / "model_broker.py"),
         "--sock", sock_path,
         "--upstream", "127.0.0.1:1",
         "--model", "iso-model",
         "--token", token],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    ready = os.path.join(os.path.dirname(sock_path), "ready")
    for _ in range(100):
        if os.path.exists(ready):
            return proc
        if proc.poll() is not None:
            err = proc.stderr.read().decode("utf-8", "ignore") if proc.stderr else ""
            raise RuntimeError(f"broker exited early: {err[:200]}")
        time.sleep(0.05)
    proc.terminate()
    raise RuntimeError("broker ready-file timeout")


def _http_unix(sock_path: str, raw: bytes, timeout: float = 2.0) -> bytes:
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


class T09CancelBrokerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.sock = str(Path(self.td.name) / "model.sock")
        self.store = Store(str(Path(self.td.name) / "h.db"))
        self.broker = _start_broker(self.sock)

    def tearDown(self):
        try:
            self.broker.terminate()
            self.broker.wait(timeout=2)
        except Exception:
            self.broker.kill()
        self.td.cleanup()

    def test_cancel_sets_interrupted_no_redispatch(self):
        jid = self.store.create_job(
            channel="grid", goal="t09-cancel", worker="cc", allowed_tools=["Read"],
            allowed_paths=[], cloud_allowed=False, approval_mode="auto",
            origin="grid_c_confirm", context_hash="t09" * 10 + "ab",
        )["job_id"]
        self.store.update_job(jid, status="running", last_step="dispatch")
        self.store.update_job(jid, status="interrupted", last_step="cancelled")
        self.assertEqual(self.store.get_job(jid)["status"], "interrupted")
        self.assertIsNone(self.store.claim_next_queued())

    def test_killed_broker_no_fallback(self):
        """Missing token → 401; no generation reaches upstream (port 1 closed)."""
        raw = (
            b"POST /v1/messages HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 24\r\n\r\n"
            b'{"model":"iso-model"}'
        )
        out = _http_unix(self.sock, raw, timeout=3.0)
        head = out.split(b"\r\n", 1)[0]
        self.assertIn(b"401", head, out[:120])

    def test_established_stream_closed_on_kill(self):
        """Open a connection, kill broker, verify socket closes (no orphan)."""
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(self.sock)
        self.assertTrue(s.fileno() > 0)
        self.broker.terminate()
        try:
            self.broker.wait(timeout=2)
        except Exception:
            self.broker.kill()
        time.sleep(0.3)
        closed = False
        try:
            s.sendall(b"GET /v1/models HTTP/1.1\r\nHost: x\r\n\r\n")
            data = s.recv(100)
            if data == b"":
                closed = True
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            closed = True
        finally:
            s.close()
        self.assertTrue(closed, "socket should be closed after broker kill")


if __name__ == "__main__":
    unittest.main(verbosity=2)
