"""Real TLS fixture + adversarial runtime tests. All external network replaced only at TCP routing/DNS.
HTTPS, certificate verification, HTTP parsing, redirects, policy and extraction execute unmodified.
"""
import datetime, gzip, io, json, os, pathlib, socket, ssl, subprocess, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
import web_fetch_v3 as w
PUBLIC='93.184.215.14'
class Handler(BaseHTTPRequestHandler):
    calls=[]
    def log_message(self,*a):pass
    def do_GET(self):
        Handler.calls.append((self.headers.get('Host'),self.path,dict(self.headers)))
        path=w.urllib.parse.urlsplit(self.path).path
        code=200;headers={};mime='text/html; charset=utf-8'
        if path=='/redirect':code=302;headers['Location']='https://other.test/page';body=b''
        elif path=='/private':code=302;headers['Location']='https://127.0.0.1/secret';body=b''
        elif path=='/deny':code=302;headers['Location']='https://blocked.test/page';body=b''
        elif path=='/loop':code=302;headers['Location']='/loop';body=b''
        elif path=='/fail':code=503;body=b'unavailable'
        elif path=='/json':mime='application/json';body=json.dumps({'message':'中文','value':4}).encode()
        elif path=='/rss':mime='application/rss+xml';body=b'<rss><channel><item><title>RSS story</title><description>Source fact</description></item></channel></rss>'
        elif path=='/dtd':mime='application/xml';body=b'<!DOCTYPE x [<!ENTITY a "boom">]><x>&a;</x>'
        elif path=='/large':body=b'x'*(w.MAX_BYTES+1)
        elif path=='/zipbomb':body=gzip.compress(b'x'*(w.MAX_BYTES+1));headers['Content-Encoding']='gzip'
        elif path=='/gzip':body=gzip.compress(b'<html><p>compressed fact</p></html>');headers['Content-Encoding']='gzip'
        elif path=='/latin':mime='text/plain; charset=iso-8859-1';body='café'.encode('latin1')
        elif path=='/echo':body=(self.headers.get('Authorization','')+' '+self.headers.get('User-Agent','')).encode();mime='text/plain'
        elif path=='/pdf':body=self.server.pdf;mime='application/pdf'
        elif path=='/empty':body=b'<html><script>only js</script></html>'
        elif path=='/html/':
            q=w.urllib.parse.parse_qs(w.urllib.parse.urlsplit(self.path).query)
            if q.get('q')==['fallback']:body=b'<form id="challenge-form">bots use DuckDuckGo</form>'
            elif 's' in q:body=b'<a href="https://source.test/two" class="result__a">Second result</a><div class="result__snippet">Second snippet</div>'
            else:body=b'''<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsource.test%2Fone" class="extra result__a"><b>First</b> result</a><a href="#" class="result__snippet">Useful <b>actual</b> snippet</a><form action="/html/" method="post"><input name="s" value="30"><input type="submit" value="Next"></form>'''
        elif path=='/search':
            mime='application/json';body=json.dumps({'results':[{'url':'https://source.test/searx-result','title':'SearXNG result','content':'Independent adapter snippet'}]}).encode()
        elif path=='/lite/':body=b'<table><tr><td><a href="https://source.test/three" class="result-link">Lite result</a></td></tr><tr><td class="result-snippet">Lite snippet</td></tr></table>'
        else:body=b'<html><title>Fixture</title><script>HIDE</script><article><p>Real TLS fact.</p><a href="/json">JSON source</a></article></html>'
        self.send_response(code);self.send_header('Content-Type',mime)
        for k,v in headers.items():self.send_header(k,v)
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        cls.tmp=tempfile.TemporaryDirectory();cls.root=pathlib.Path(cls.tmp.name)
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'source.test')]);now=datetime.datetime.now(datetime.timezone.utc)
        names=['source.test','other.test','auth.test','blocked.test','html.duckduckgo.com','lite.duckduckgo.com','sub.source.test']
        cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in names]),False).add_extension(x509.BasicConstraints(ca=True,path_length=None),True).sign(key,hashes.SHA256())
        (cls.root/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM));(cls.root/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption()))
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(cls.root/'cert.pem',cls.root/'key.pem');cls.server.socket=ctx.wrap_socket(cls.server.socket,server_side=True)
        from reportlab.pdfgen import canvas
        buffer=io.BytesIO();c=canvas.Canvas(buffer);c.drawString(72,720,'PDF source fact');c.save();cls.server.pdf=buffer.getvalue()
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.real_connect=staticmethod(socket.create_connection);cls.real_context=staticmethod(ssl.create_default_context);cls.real_gai=staticmethod(socket.getaddrinfo)
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.tmp.cleanup()
    def setUp(self):
        Handler.calls.clear();w._rates.clear();self.checked=[]
        self.eg=self.root/'EGRESS.md';self.eg.write_text('''| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |
| * | open | yes | none | 1000 | attested | TEST | research,scout |
| source.test | source | yes | none | 1000 | attested | TEST | research |
| auth.test | auth | yes | SECRET_TOKEN | 1000 | issuer_claim | TEST | research |
| *.source.test | children | yes | none | 1000 | secondhand | TEST | research |
[deny]
blocked.test
''')
        def gai(host,port,*args,**kwargs):
            if host==PUBLIC or host=='127.0.0.1':return self.real_gai(host,port,*args,**kwargs)
            try:
                ip=w.ipaddress.ip_address(host);value=str(ip)
            except ValueError:value=PUBLIC
            return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(value,443))]
        def dial(address,timeout=None,*args,**kwargs):
            self.checked.append(address);self.assertEqual(address,(PUBLIC,443))
            return self.real_connect(('127.0.0.1',self.server.server_port),timeout)
        for p in [patch.object(socket,'getaddrinfo',side_effect=gai),patch.object(socket,'create_connection',side_effect=dial),patch.object(ssl,'create_default_context',side_effect=lambda:self.real_context(cafile=str(self.root/'cert.pem'))),patch.dict(os.environ,{'SECRET_TOKEN':'EXAMPLE_SECRET'})]:
            p.start();self.addCleanup(p.stop)
    def fetch(self,path,host='source.test',**kwargs):return w.fetch('https://'+host+path,'research',egress_path=str(self.eg),**kwargs)
    def test_real_tls_html_links(self):
        r=self.fetch('/page');self.assertTrue(r['ok'],r);self.assertIn('Real TLS fact',r['text']);self.assertNotIn('HIDE',r['text']);self.assertEqual(r['grade'],'attested');self.assertEqual(r['links'][0]['url'],'https://source.test/json');self.assertTrue(self.checked)
    def test_json_rss_latin_gzip(self):
        for p,needle in [('/json','中文'),('/rss','Source fact'),('/latin','café'),('/gzip','compressed fact')]:
            r=self.fetch(p);self.assertTrue(r['ok'],r);self.assertIn(needle,r['text'])
    def test_pdf_real_response(self):
        r=self.fetch('/pdf');self.assertTrue(r['ok'],r);self.assertIn('PDF source fact',r['text']);self.assertEqual(r['pages_read'],1)
    def test_redirect_rechecks_grade_and_auth(self):
        r=self.fetch('/redirect','auth.test');self.assertTrue(r['ok'],r);self.assertEqual(r['grade'],'unverified')
        self.assertEqual(Handler.calls[0][2]['Authorization'],'Bearer EXAMPLE_SECRET');self.assertNotIn('Authorization',Handler.calls[1][2]);self.assertEqual(len(r['redirects']),2)
    def test_redirect_private_deny_loop(self):
        for p,state,count in [('/private','DENIED',1),('/deny','DENIED',1),('/loop','REDIRECT_LIMIT',4)]:
            Handler.calls.clear();r=self.fetch(p);self.assertEqual(r['status'],state,r);self.assertEqual(len(Handler.calls),count)
    def test_address_and_authority_attacks(self):
        for url in ['http://source.test/','https://user:pass@source.test/','https://127.0.0.1/','https://[::1]/','https://169.254.169.254/','https://100.64.0.1/','https://source.test:8443/','https://blocked.test./','https://sub.blocked.test/']:
            r=w.fetch(url,'research',egress_path=str(self.eg));self.assertEqual(r['status'],'DENIED',r)
        self.assertEqual(Handler.calls,[])
    def test_dns_mixed_public_private(self):
        with patch.object(socket,'getaddrinfo',return_value=[(2,1,6,'',(PUBLIC,443)),(2,1,6,'',('10.0.0.1',443))]):
            self.assertEqual(self.fetch('/page')['status'],'DENIED')
        self.assertEqual(Handler.calls,[])
    def test_dns_pinning_no_second_hostname_lookup(self):
        with patch.object(socket,'getaddrinfo',side_effect=lambda host,*args,**kwargs: self.real_gai(host,*args,**kwargs) if host=='127.0.0.1' else [(2,1,6,'',(PUBLIC,443))]) as gai:
            self.assertTrue(self.fetch('/page')['ok']);self.assertEqual(sum(c.args[0]=='source.test' for c in gai.call_args_list),1)
        self.assertEqual(self.checked,[(PUBLIC,443)])
    def test_tls_wrong_hostname_rejected(self):
        self.assertFalse(self.fetch('/page','wrong.test')['ok']);self.assertEqual(Handler.calls,[])
    def test_size_and_xml_expansion(self):
        for p,state in [('/large','TOO_LARGE'),('/zipbomb','TOO_LARGE'),('/dtd','XML_DTD_FORBIDDEN'),('/fail','HTTP 503'),('/empty','EMPTY_CONTENT')]:self.assertEqual(self.fetch(p)['status'],state)
    def test_filter_bounded_and_secrets(self):
        r=self.fetch('/echo','auth.test',signal_filter=lambda s:s*100,max_chars=50)
        self.assertTrue(r['ok']);self.assertNotIn('EXAMPLE_SECRET',json.dumps(r));self.assertLessEqual(r['chars'],55);self.assertTrue(r['truncated'])
        self.assertEqual(self.fetch('/page',max_chars=-1)['status'],'DENIED')
    def test_specific_lane_does_not_fall_through_star(self):
        self.assertEqual(w.fetch('https://source.test/page','scout',egress_path=str(self.eg))['status'],'DENIED')
        self.assertEqual(self.fetch('/page','sub.source.test')['grade'],'secondhand')
    def test_rate_is_enforced(self):
        self.eg.write_text(self.eg.read_text().replace('none | 1000 | attested | TEST | research |','none | 1 | attested | TEST | research |'))
        self.assertTrue(self.fetch('/page')['ok']);self.assertEqual(self.fetch('/page')['status'],'RATE_LIMITED');self.assertEqual(len(Handler.calls),1)
    def test_search_pagination_snippet_lite(self):
        r=w.search('grid','research',n=3,egress_path=str(self.eg));self.assertTrue(r['ok'],r);self.assertEqual(len(r['results']),3)
        self.assertEqual(r['results'][0]['snippet'],'Useful actual snippet');self.assertEqual(r['results'][1]['page'],2);self.assertEqual(r['results'][2]['provider'],'ddg_lite')
    def test_search_challenge_fallback(self):
        r=w.search('fallback','research',n=1,egress_path=str(self.eg));self.assertTrue(r['ok'],r);self.assertEqual(r['attempts'][0]['status'],'SEARCH_CHALLENGE');self.assertEqual(r['results'][0]['provider'],'ddg_lite')
    def test_search_denied_and_size_shared(self):
        r=w.search('grid','forbidden',egress_path=str(self.eg));self.assertFalse(r['ok']);self.assertEqual(Handler.calls,[])
        with patch.dict(w.SEARCH_ENDPOINTS,{'ddg_html':'https://source.test/large'}):
            r=w.search('grid','research',providers=('ddg_html',),egress_path=str(self.eg));self.assertEqual(r['status'],'TOO_LARGE')
    def test_many_deduplicates_and_preserves_order(self):
        r=w.fetch_many(['https://source.test/json','https://source.test/rss','https://source.test/json'],'research',egress_path=str(self.eg));self.assertEqual(len(r),2);self.assertEqual([x['format'] for x in r],['json','xml'])
        r=w.search_many(['grid','fallback'],'research',n=3,egress_path=str(self.eg));self.assertEqual(len(r['results']),3);self.assertEqual(r['results'][1]['query'],'fallback')
    def test_searxng_json_adapter(self):
        r=w.search('grid','research',n=1,providers=('searxng',),searxng_url='https://source.test/search',egress_path=str(self.eg))
        self.assertTrue(r['ok'],r);self.assertEqual(r['results'][0]['provider'],'searxng');self.assertIn('format=json',Handler.calls[0][1]);self.assertIn('pageno=1',Handler.calls[0][1])
    def test_pdf_malformed_and_timeout(self):
        with self.assertRaises(w.FetchFailure):w._extract(b'%PDF-BROKEN',{'content-type':'application/pdf'},'https://source.test/pdf')
        with patch.object(w.subprocess,'run',side_effect=subprocess.TimeoutExpired('pdf',1)):
            self.assertEqual(self.fetch('/pdf')['status'],'PDF_PARSE_TIMEOUT')
    def test_failed_receipt_masks_registered_secret(self):
        r=self.fetch('/private?opaque=EXAMPLE_SECRET','auth.test');self.assertEqual(r['status'],'DENIED');self.assertNotIn('EXAMPLE_SECRET',json.dumps(r))
    def test_search_then_fetch_e2e(self):
        found=w.search('grid','research',n=3,egress_path=str(self.eg))
        receipts=w.fetch_many([r['url'] for r in found['results']],'research',egress_path=str(self.eg))
        self.assertEqual(len(receipts),3);self.assertTrue(all(r['ok'] for r in receipts),receipts);self.assertTrue(all('Real TLS fact' in r['text'] for r in receipts))
    def test_audit_failure_visible(self):
        r=self.fetch('/page',db_path='EXAMPLE.db');self.assertEqual(r.get('audit_warning'),'tool_log_failed')
    def test_default_template_not_self_authorizing(self):
        self.eg.write_text(w.EGRESS_TEMPLATE);self.assertEqual(self.fetch('/page')['status'],'DENIED');self.assertEqual(Handler.calls,[])
    def test_legacy_override_cannot_disable_real_transport_check(self):
        r=w.fetch('https://127.0.0.1/','research',egress_path=str(self.eg),_private_check=lambda h:False);self.assertEqual(r['status'],'DENIED');self.assertEqual(Handler.calls,[])
if __name__=='__main__':unittest.main(verbosity=2)
