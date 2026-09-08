"""T11: audit failure injection, UI/log receives degraded marker.

Isolated audit DB made unwritable. Real fetch path (TLS routed to a
local fixture) runs, audit log fails, response carries
`audit_warning='tool_log_failed'`. Verifies the failure is visible
(not silently swallowed) and the fetch still succeeds.
"""
from __future__ import annotations
import datetime, json, os, pathlib, socket, ssl, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_fetch_v3 as w

PUBLIC = "93.184.215.14"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = b"<html><p>Real TLS fact.</p></html>"
        self.send_response(200); self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        try: self.wfile.write(body)
        except Exception: pass


class T11AuditFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        cls.tmp = tempfile.TemporaryDirectory(); cls.root = pathlib.Path(cls.tmp.name)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "source.test")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("source.test")]), False)
                .sign(key, hashes.SHA256()))
        (cls.root / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (cls.root / "key.pem").write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cls.root / "cert.pem", cls.root / "key.pem")
        cls.server.socket = ctx.wrap_socket(cls.server.socket, server_side=True)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.real_connect = staticmethod(socket.create_connection)
        cls.real_context = staticmethod(ssl.create_default_context)
        cls.real_gai = staticmethod(socket.getaddrinfo)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.tmp.cleanup()

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.eg = pathlib.Path(self.td.name) / "egress.md"
        self.eg.write_text(
            "| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |\n"
            "| source.test | source | yes | none | 1000 | attested | TEST | research |\n",
            encoding="utf-8")
        self.audit_db = pathlib.Path(self.td.name) / "audit.db"
        self.audit_db.touch()
        os.chmod(self.audit_db, 0o444)
        self._patches = [
            patch.object(socket, "getaddrinfo", side_effect=self._gai),
            patch.object(socket, "create_connection", side_effect=self._dial),
            patch.object(ssl, "create_default_context",
                        side_effect=lambda: self.real_context(cafile=str(self.root / "cert.pem"))),
        ]
        for p in self._patches:
            p.start(); self.addCleanup(p.stop)

    def tearDown(self):
        os.chmod(self.audit_db, 0o644)
        self.td.cleanup()

    def _gai(self, host, port, *a, **k):
        if host == PUBLIC or host == "127.0.0.1":
            return self.real_gai(host, port, *a, **k)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 443))]

    def _dial(self, address, timeout=None, *a, **k):
        return self.real_connect(("127.0.0.1", self.port), timeout)

    def test_audit_failure_visible(self):
        r = w.fetch("https://source.test/page", "research",
                    egress_path=str(self.eg), db_path=str(self.audit_db))
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r.get("audit_warning"), "tool_log_failed")
        self.assertIn("Real TLS fact", r.get("text", ""))

    def test_audit_failure_does_not_block_fetch(self):
        """Audit failure is non-fatal: fetch still returns content."""
        r = w.fetch("https://source.test/page", "research",
                    egress_path=str(self.eg), db_path=str(self.audit_db))
        self.assertTrue(r.get("ok"))
        self.assertEqual(r.get("audit_warning"), "tool_log_failed")

    def test_no_audit_db_no_warning(self):
        """When db_path is None, no audit attempt, no warning."""
        r = w.fetch("https://source.test/page", "research",
                    egress_path=str(self.eg), db_path=None)
        self.assertTrue(r.get("ok"))
        self.assertNotIn("audit_warning", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
