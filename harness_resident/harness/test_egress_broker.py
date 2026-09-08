#!/usr/bin/env python3
"""TEST: egress broker rejects illegal fields before calling web_fetch_v2."""
from __future__ import annotations
import json, os, socket, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


class EgressBrokerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.sock = str(Path(self.td.name) / "egress.sock")
        self.fake = Path(self.td.name) / "web_fetch_v2.py"
        self.hits = Path(self.td.name) / "hits.json"
        self.hits.write_text("[]", encoding="utf-8")
        self.fake.write_text(
            "import json, pathlib\n"
            "HITS=pathlib.Path(%r)\n"
            "MAX_CHARS=8000\n"
            "def _hit(name,**kw):\n"
            "    rows=json.loads(HITS.read_text()); rows.append(name); HITS.write_text(json.dumps(rows))\n"
            "    return {'ok':True,'status':'TEST','action':name}\n"
            "def fetch(*a,**k): return _hit('fetch')\n"
            "def search(*a,**k): return _hit('search')\n"
            "def search_many(*a,**k): return _hit('search_many')\n"
            "def fetch_many(*a,**k): return _hit('fetch_many')\n" % str(self.hits),
            encoding="utf-8",
        )
        env = dict(os.environ)
        env.update({
            "EGRESS_SOCK": self.sock,
            "BOUND_LANE": "cc",
            "EGRESS_PATH": "/etc/egress/EGRESS.md",
            "BOUND_JOB_ID": "TEST-job",
            "WEB_FETCH_DIR": self.td.name,
        })
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "sandbox" / "egress_broker.py")],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env,
        )
        for _ in range(50):
            if Path(self.td.name, "egress.ready").exists() and Path(self.sock).exists():
                break
            time.sleep(0.05)
        else:
            self.fail("egress broker did not bind")

    def tearDown(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()
        self.td.cleanup()

    def _hits(self):
        return json.loads(self.hits.read_text(encoding="utf-8"))

    def _post(self, obj, path=b"/action"):
        body = json.dumps(obj).encode()
        raw = (
            b"POST " + path + b" HTTP/1.1\r\nHost: x\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode() + body
        )
        return _http(self.sock, raw)

    def test_connect_zero_fetch(self):
        out = _http(self.sock, b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 405"), out[:80])
        time.sleep(0.05)
        self.assertEqual(self._hits(), [])

    def test_transfer_encoding_zero_fetch(self):
        out = _http(self.sock, b"POST /action HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 400"), out[:80])
        self.assertEqual(self._hits(), [])

    def test_forge_lane_rejected(self):
        out = self._post({"action": "fetch", "url": "https://example.com", "lane": "research"})
        self.assertTrue(out.startswith(b"HTTP/1.1 400"), out[:80])
        self.assertEqual(self._hits(), [])

    def test_opener_rejected(self):
        out = self._post({"action": "fetch", "url": "https://example.com", "opener": True})
        self.assertTrue(out.startswith(b"HTTP/1.1 400"), out[:80])
        self.assertEqual(self._hits(), [])

    def test_unknown_action_rejected(self):
        out = self._post({"action": "shell", "cmd": "id"})
        self.assertTrue(out.startswith(b"HTTP/1.1 4"), out[:80])
        self.assertEqual(self._hits(), [])

    def test_fetch_ok_calls_stub(self):
        out = self._post({"action": "fetch", "url": "https://example.com"})
        self.assertIn(b"HTTP/1.1 200", out)
        self.assertEqual(self._hits(), ["fetch"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
