import http.server
import json
import threading
import unittest
from harness.option_shadow_ledger import Theta, ThetaError

class Handler(http.server.BaseHTTPRequestHandler):
    code=200
    payload=b'[{"symbol":"SPY","expiration":"2026-09-11"}]'
    def do_GET(self):
        self.send_response(self.code)
        if self.code==302: self.send_header('Location','http://127.0.0.1:1/forbidden')
        self.end_headers(); self.wfile.write(self.payload)
    def log_message(self,*args): pass

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.handler=type('PerTestHandler',(Handler,),{})
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),self.handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.th=Theta(base=f'http://127.0.0.1:{self.server.server_port}')
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
    def test_real_http_fixture(self): self.assertEqual(self.th.expirations('SPY'),['2026-09-11'])
    def test_http_error_not_down(self):
        self.handler.code=403
        with self.assertRaisesRegex(ThetaError,'http_403'): self.th.expirations('SPY')
    def test_redirect_not_followed(self):
        self.handler.code=302
        with self.assertRaisesRegex(ThetaError,'redirect_refused'): self.th.expirations('SPY')
    def test_empty_result_valid(self):
        self.handler.payload=b'[]'
        self.assertEqual(self.th.expirations('SPY'),[])
