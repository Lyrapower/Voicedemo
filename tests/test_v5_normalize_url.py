import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness_resident"))
from harness.web_fetch_normalize import normalize_url as n
def test_space(): assert n('https://api.grants.gov/v1/api/search2?keyword=clean energy&rows=10')[0].endswith('keyword=clean%20energy&rows=10')
def test_json_escapes(): assert n('"https:\\/\\/api.grants.gov\\/v1\\/api\\/fetchOpportunity?oppId=359123\\""')[0]=='https://api.grants.gov/v1/api/fetchOpportunity?oppId=359123'
def test_bad(): assert n('ht tp://x')[0] is None and n('api.grants.gov/v1')[0] is None
def test_idempotent():
    u,_=n('https://x.org/a b?q=c d'); assert n(u)[0]==u
