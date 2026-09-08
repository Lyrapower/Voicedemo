#!/usr/bin/env python3
"""TEST: dev CONNECT rejects unapproved/private/malformed before upstream."""
from __future__ import annotations
import os, socket, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _http(sock_path, raw, timeout=2.0):
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


class DevBrokerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.sock = str(Path(self.td.name) / "dev.sock")
        man = Path(self.td.name) / "DEV.md"
        man.write_text("| host | port | protocol | 拍板 | lanes |\n|---|---|---|---|---|\n| example.com | 443 | CONNECT | 2026-09-07 | cc_dev |\n", encoding="utf-8")
        env = dict(os.environ)
        env.update({"DEV_SOCK": self.sock, "DEV_PATH": str(man)})
        self.proc = subprocess.Popen(
            [sys.executable, "-c",
             "import os,sys; sys.path.insert(0, os.environ['DEV_MOD']); import dev_broker as d; "
             "d.serve(os.environ['DEV_SOCK'], os.environ['DEV_PATH'], fake_up=True)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            env={**env, "DEV_MOD": str(ROOT / "sandbox")})
        for _ in range(50):
            if Path(self.td.name, "dev.ready").exists():
                break
            time.sleep(0.05)
        else:
            self.fail("dev broker bind")

    def tearDown(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()
        self.td.cleanup()

    def test_unapproved_host(self):
        out = _http(self.sock, b"CONNECT evil.com:443 HTTP/1.1\r\nHost: evil.com:443\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 403"), out[:80])

    def test_malformed_absolute(self):
        out = _http(self.sock, b"CONNECT https://example.com HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 400"), out[:80])

    def test_non_connect(self):
        out = _http(self.sock, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 405"), out[:80])

    def test_allowed_counts_fake_upstream(self):
        out = _http(self.sock, b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
        self.assertIn(b"200", out[:40])

    def test_production_env_fake_exits(self):
        env = dict(os.environ)
        env["DEV_FAKE_UPSTREAM"] = "1"
        env["DEV_SOCK"] = str(Path(self.td.name) / "prod.sock")
        env["DEV_PATH"] = str(Path(self.td.name) / "DEV.md")
        r = subprocess.run([sys.executable, str(ROOT / "sandbox" / "dev_broker.py")],
                           capture_output=True, text=True, env=env, timeout=5)
        self.assertEqual(r.returncode, 78)
        self.assertIn("BLOCKED_TEST_OVERRIDE", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
