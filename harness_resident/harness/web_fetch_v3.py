"""Grid web fetch v3: bounded discovery + HTTPS fetch. Compatible fetch/search call signatures.
No JS/browser execution. EGRESS remains authoritative. See README for coverage and limits.
"""
from __future__ import annotations
import concurrent.futures, gzip, html, http.client, io, ipaddress, json, os, re, socket, ssl, threading, time, subprocess, sys
import urllib.error, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from html.parser import HTMLParser

MAX_CHARS=int(os.getenv('WEB_FETCH_MAX_CHARS','12000'))
MAX_BYTES=int(os.getenv('WEB_FETCH_MAX_BYTES','2000000'))
TIMEOUT=float(os.getenv('WEB_FETCH_TIMEOUT','15'))
MAX_REDIRECTS=3
CATALOG_SEARCH2='https://api.grants.gov/v1/api/search2'
CATALOG_FETCH_OPP='https://api.grants.gov/v1/api/fetchOpportunity'
CATALOG_POST_URLS=frozenset({CATALOG_SEARCH2, CATALOG_FETCH_OPP})
GITHUB_SEARCH_PATH='/search/repositories'
GRADES={'attested','witnesses_agree','witness_only','issuer_claim','secondhand','unverified'}
SEARCH_HOST='html.duckduckgo.com'
SEARCH_ENDPOINTS={
    'ddg_html':'https://html.duckduckgo.com/html/',
    'ddg_lite':'https://lite.duckduckgo.com/lite/',
    'ddg_api':'https://api.duckduckgo.com/',
    'wikipedia':'https://en.wikipedia.org/w/api.php',
    'github':'https://api.github.com/search/repositories',
}
EGRESS_TEMPLATE='''# EGRESS.md: approval cells intentionally empty; edit your existing registry explicitly.
| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |
|---|---|---|---|---|---|---|---|
| * | 开放网研究读取 | yes | none | 30 | unverified | | research,deep,full,cc,scout |
| html.duckduckgo.com | 搜索 HTML | yes | none | 20 | unverified | | research,deep,full,cc,scout |
| lite.duckduckgo.com | 搜索备用 Lite | yes | none | 20 | unverified | | research,deep,full,cc,scout |
| data.sec.gov | SEC JSON | yes | SEC_UA | 10 | attested | | research,rwa,deep,full |
| export.arxiv.org | arXiv feed | yes | none | 20 | issuer_claim | | research,deep,full |
# 可用 *.example.org 显式授权其子域；不包含 example.org 本身。
[deny]
'''

class Rejected(Exception):
    def __init__(self, msg, matched_rule=None, match_kind=None):
        super().__init__(msg)
        self.matched_rule = matched_rule
        self.match_kind = match_kind
class FetchFailure(Exception): pass

def _host(host):
    host=(host or '').rstrip('.').lower()
    try:return ipaddress.ip_address(host).compressed
    except ValueError:return host.encode('idna').decode('ascii')

def _url(url):
    if not isinstance(url,str) or any(ord(c)<33 or ord(c)==127 for c in url) or '\\' in url:
        raise Rejected('invalid URL')
    u=urllib.parse.urlsplit(url)
    if u.scheme.lower()!='https' or not u.hostname or u.username is not None or u.password is not None:
        raise Rejected('HTTPS required; URL credentials forbidden')
    try:port=u.port or 443;host=_host(u.hostname)
    except (ValueError,UnicodeError):raise Rejected('invalid host/port')
    if port!=443:raise Rejected('only HTTPS port 443 allowed')
    if '%' in host:raise Rejected('scoped address forbidden')
    authority='['+host+']' if ':' in host else host
    return urllib.parse.urlunsplit(('https',authority,u.path or '/',u.query,'')),host

def _safe_url(url,secrets=()):
    try:
        u=urllib.parse.urlsplit(str(url));host=_host(u.hostname)
        if not host:return '[invalid URL]'
        query=[]
        for k,v in urllib.parse.parse_qsl(u.query,keep_blank_values=True):
            if re.search(r'key|token|secret|password|auth|signature|credential',k,re.I) or any(s and s in v for s in secrets):v='[REDACTED]'
            query.append((k,v))
        result=urllib.parse.urlunsplit((u.scheme,'['+host+']' if ':' in host else host,u.path,urllib.parse.urlencode(query),''))
        for s in secrets:
            if s:result=result.replace(s,'[REDACTED]').replace(urllib.parse.quote(s,safe=''),'[REDACTED]')
        return result
    except Exception:return '[invalid URL]'

def _normalize_domain_cell(raw):
    domain=(raw or '').lower().rstrip('.')
    if domain=='*':
        return domain
    if domain.startswith('*.'):
        return '*.'+_host(domain[2:])
    return _host(domain)

def _row_active(ro, grade, approved, rate):
    try:
        rate_i=int(rate)
    except (TypeError, ValueError):
        return False, 0, True
    if rate_i<1:
        return False, rate_i, True
    malformed = grade not in GRADES or str(ro).lower()!='yes'
    active = bool(str(approved or '').strip()) and not malformed
    return active, rate_i, malformed

def load_egress(path='EGRESS.md'):
    out={'rows':{},'star':None,'deny':[],'warnings':[],'errors':[],'config_error':None}
    deny=False
    if not os.path.exists(path):return out
    with open(path,encoding='utf-8') as f:
        for line in f:
            s=line.strip()
            if s.lower()=='[deny]':deny=True;continue
            if deny:
                if s and not s.startswith(('#','|')):
                    try:out['deny'].append(_host(s.lstrip('.')))
                    except (ValueError,UnicodeError):out['errors'].append('invalid deny host')
                continue
            if not s.startswith('|'):continue
            cells=[x.strip() for x in s.strip('|').split('|')]
            if len(cells)<8 or cells[0] in ('domain','---'):continue
            domain_raw,purpose,ro,auth,rate,grade,approved,lanes=cells[:8]
            try:
                domain=_normalize_domain_cell(domain_raw)
            except (ValueError,UnicodeError):
                out['errors'].append('unparseable registration domain')
                continue
            active, rate_i, malformed=_row_active(ro, grade, approved, rate)
            row={
                'domain':domain,'purpose':purpose,
                'auth_env':None if auth.lower() in ('none','') else auth,
                'rate':rate_i if rate_i>=1 else 0,
                'grade':grade,'approved':approved,
                'lanes':[x.strip() for x in lanes.split(',') if x.strip()],
                'active':active,'malformed':malformed,
            }
            if domain=='*':
                row.update(grade='unverified',auth_env=None)
                if out['star'] is not None:
                    prev=out['star']
                    if (prev.get('active'), prev.get('lanes'), prev.get('approved')) != (row['active'], row['lanes'], row['approved']):
                        out['config_error']='duplicate conflicting registration: *'
                    out['warnings'].append('duplicate * row')
                    if prev.get('active') and not row['active']:
                        out['star']=row
                    continue
                out['star']=row
                continue
            if domain in out['rows']:
                prev=out['rows'][domain]
                if (prev.get('active'), prev.get('lanes'), prev.get('auth_env'), prev.get('approved')) != (
                        row['active'], row['lanes'], row['auth_env'], row['approved']):
                    out['config_error']=f'duplicate conflicting registration: {domain}'
                out['warnings'].append(f'duplicate registration {domain}')
                if prev.get('active') and not row['active']:
                    out['rows'][domain]=row
                continue
            out['rows'][domain]=row
    if out['errors'] and not out['config_error']:
        out['config_error']=out['errors'][0]
    return out

def _check_matched_row(row, lane, match_kind):
    meta={'matched_rule':row.get('domain'),'match_kind':match_kind,'approved':row.get('approved') or ''}
    if row.get('malformed'):
        return None,'malformed registration',meta
    if not row.get('active') or not str(row.get('approved') or '').strip():
        return None,'registration pending/unapproved',meta
    if row.get('lanes') and lane not in row['lanes']:
        return None,'lane not allowed for this source',meta
    return row,None,meta

def _resolve_row(reg,host,lane):
    if reg.get('config_error'):
        return None,'egress config error: '+str(reg['config_error']),{'matched_rule':None,'match_kind':'config'}
    h=_host(host)
    for suffix in reg['deny']:
        if h==suffix or h.endswith('.'+suffix):
            return None,'domain denied',{'matched_rule':suffix,'match_kind':'deny'}
    if h in reg['rows']:
        return _check_matched_row(reg['rows'][h], lane, 'exact')
    matches=[(len(k),v) for k,v in reg['rows'].items() if k.startswith('*.') and h.endswith(k[1:])]
    if matches:
        return _check_matched_row(max(matches,key=lambda x:x[0])[1], lane, 'wildcard')
    if reg.get('star'):
        return _check_matched_row(reg['star'], lane, 'star')
    return None,'domain not approved (no active wildcard)',{'matched_rule':None,'match_kind':None}

def _public_ips(host):
    try:infos=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    except socket.gaierror:raise FetchFailure('DNS_FAILED') from None
    ips=list(dict.fromkeys(ai[4][0] for ai in infos))
    if not ips:raise Rejected('DNS returned no addresses')
    for value in ips:
        ip=ipaddress.ip_address(value)
        if not ip.is_global or ip.is_multicast or ip.is_reserved or getattr(ip,'ipv4_mapped',None) or getattr(ip,'sixtofour',None) or getattr(ip,'teredo',None):
            raise Rejected('non-public or transition address forbidden')
    return ips

def _is_private_host(host):
    try:_public_ips(_host(host));return False
    except Exception:return True

def _ssl_ctx():
    # Python.org 3.13 on this host has an empty default CA path; v1 used certifi.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,ips,timeout):
        super().__init__(host,443,timeout=timeout,context=_ssl_ctx());self.ips=ips
    def connect(self):
        # DNS checked once, connection uses those exact IPs; TLS authenticates original hostname.
        deadline=time.monotonic()+self.timeout
        for ip in self.ips:
            raw=None
            try:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError()
                raw=socket.create_connection((ip,443),remaining)
                self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
                return
            except Exception:
                if raw:raw.close()
        raise FetchFailure('CONNECT_FAILED')

_rate_lock=threading.Lock();_rates={}
def _rate(path,row,host):
    key=(os.path.realpath(path),row['domain'],host);now=time.monotonic()
    with _rate_lock:
        active=[t for t in _rates.get(key,[]) if now-t<60]
        if len(active)>=row['rate']:return False
        active.append(now);_rates[key]=active
        if len(_rates)>4096:
            for k in list(_rates):
                if _rates[k] and now-_rates[k][-1]>=60:del _rates[k]
    return True

def _log(db_path,route_id,mission_id,substrate,tool,url,chars,truncated,grade,status,lane=None):
    if not db_path:return None
    try:
        try:
            from . import harness_contract_v1 as HC
        except ImportError:
            import harness_contract_v1 as HC
        HC.log_tool_call(db_path,route_id or '',substrate or '',tool,{'url_host':urllib.parse.urlsplit(url).hostname},None,chars,truncated,mission_id=mission_id,evidence_grade=grade,status=status,lane=lane or substrate or '')
        return None
    except Exception:return 'tool_log_failed'

def _github_loader_authorized():
    try:
        from github_research_secret import loader_authorized
        return bool(loader_authorized())
    except Exception:
        try:
            from .github_research_secret import loader_authorized
            return bool(loader_authorized())
        except Exception:
            return False

def _github_auth_allowed(host, path, method):
    if not _github_loader_authorized():
        return False, 'required auth environment missing'
    if method != 'GET':
        return False, 'github auth method not allowed'
    if host != 'api.github.com':
        return False, 'github auth host not allowed'
    if path == GITHUB_SEARCH_PATH:
        return True, None
    # read-only repo metadata: GET /repos/{owner}/{repo} (no further sub-path)
    if path.startswith('/repos/'):
        rest = path[len('/repos/'):]
        if rest and '/' in rest and rest.count('/') == 1 and not rest.endswith('/'):
            return True, None
    return False, 'github auth path not allowed'


def _auth_header(row, host, path, method):
    if not row.get('auth_env'):
        return {}, []
    if row['auth_env'] == 'GITHUB_TOKEN':
        ok, why = _github_auth_allowed(host, path, method)
        if not ok:
            raise Rejected(why)
    val = os.getenv(row['auth_env'])
    if not val:
        raise Rejected('required auth environment missing')
    if '\r' in val or '\n' in val:
        raise Rejected('invalid auth header')
    if row['auth_env'] == 'SEC_UA':
        return {'User-Agent': val}, [val]
    if row['auth_env'] == 'GITHUB_TOKEN':
        return {'Authorization': 'Bearer ' + val}, [val]
    return {'Authorization': 'Bearer ' + val}, [val]


def _request(url,lane,*,egress_path,opener=None,_private_check=None,method='GET',data=None,max_redirects=None):
    reg=load_egress(egress_path);cur=url;trace=[];secrets=[];deadline=time.monotonic()+TIMEOUT
    method=(method or 'GET').upper()
    if method not in {'GET','HEAD','POST'}:
        raise Rejected('method not allowed')
    if max_redirects is None:
        max_redirects = 0 if method=='POST' else MAX_REDIRECTS
    if method=='POST':
        canon,_=_url(url)
        if canon not in CATALOG_POST_URLS:
            raise Rejected('POST not allowlisted')
        if data is None:
            raise Rejected('POST body required')
    if _private_check is not None and opener is None:raise Rejected('private-check override requires test opener')
    body=None
    if data is not None:
        if isinstance(data, (dict, list)):
            body=json.dumps(data, ensure_ascii=False, separators=(',',':')).encode('utf-8')
        elif isinstance(data, bytes):
            body=data
        else:
            body=str(data).encode('utf-8')
        if len(body)>8192:
            raise Rejected('POST body too large')
    for hop in range(max_redirects+1):
        cur,host=_url(cur);row,why,meta=_resolve_row(reg,host,lane)
        if not row:raise Rejected(why, matched_rule=(meta or {}).get('matched_rule'), match_kind=(meta or {}).get('match_kind'))
        row=dict(row);row['matched_rule']=(meta or {}).get('matched_rule');row['match_kind']=(meta or {}).get('match_kind')
        if opener is not None and _private_check is not None:
            if _private_check(host):raise Rejected('non-public address forbidden')
            ips=[]
        else:ips=_public_ips(host)
        u=urllib.parse.urlsplit(cur)
        path=u.path or '/'
        headers={'User-Agent':'grid-fetch/3','Accept':'text/html,application/json,application/xml,application/pdf,text/plain,*/*;q=0.5','Accept-Encoding':'gzip'}
        extra, used = _auth_header(row, host, path, method)
        headers.update(extra); secrets.extend(used)
        if method=='POST':
            headers['Content-Type']='application/json'
            headers['Accept']='application/json'
        if not _rate(egress_path,row,host):raise FetchFailure('RATE_LIMITED')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise FetchFailure('TIMEOUT')
        conn=None;response=None
        try:
            if opener is not None:
                req=urllib.request.Request(cur,headers=headers,method=method,data=body if method=='POST' else None)
                try:response=opener(req,timeout=remaining)
                except urllib.error.HTTPError as e:response=e
                landed=getattr(response,'geturl',lambda:cur)() or cur
                if _url(landed)[0]!=cur:raise Rejected('test opener silently followed redirect')
            else:
                conn=_PinnedHTTPS(host,ips,remaining)
                conn.request(method,path+('?' + u.query if u.query else ''),body=body if method=='POST' else None,headers=headers);response=conn.getresponse()
            status=getattr(response,'status',None) or getattr(response,'code',200)
            rh={k.lower():v for k,v in response.headers.items()}
            trace.append({'url':_safe_url(cur,secrets),'status':status,'grade':row['grade']})
            if status in (301,302,303,307,308):
                if hop==max_redirects or not rh.get('location'):raise FetchFailure('REDIRECT_LIMIT')
                nxt=urllib.parse.urljoin(cur,rh['location'])
                nxt_url,nxt_host=_url(nxt)
                if nxt_host!=host:
                    secrets.clear()
                cur=nxt;body=None;method='GET' if status in (301,302,303) else method
                continue
            if status<200 or status>=300:raise FetchFailure('HTTP '+str(status))
            chunks=[];total=0
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise FetchFailure('TIMEOUT')
                if conn and conn.sock:conn.sock.settimeout(remaining)
                reader=getattr(response,'read1',None) or response.read
                chunk=reader(min(65536,MAX_BYTES+1-total))
                if not chunk:break
                total+=len(chunk)
                if total>MAX_BYTES:raise FetchFailure('TOO_LARGE')
                chunks.append(chunk)
            raw=b''.join(chunks)
        finally:
            if response and hasattr(response,'close'):response.close()
            if conn:conn.close()
        if rh.get('content-encoding','').lower()=='gzip':
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:raw=gz.read(MAX_BYTES+1)
            except Exception:raise FetchFailure('BAD_GZIP')
            if len(raw)>MAX_BYTES:raise FetchFailure('TOO_LARGE')
        elif rh.get('content-encoding','identity').lower()!='identity':raise FetchFailure('UNSUPPORTED_ENCODING')
        return raw,rh,cur,row,trace,secrets,status
    raise FetchFailure('REDIRECT_LIMIT')

class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.title=[];self.links=[];self.skip=0;self.in_title=False;self.anchor=None
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag in ('script','style','noscript','template'):self.skip+=1
        if self.skip:return
        if tag=='title':self.in_title=True
        if tag in ('p','div','section','article','br','li','h1','h2','h3','tr'):self.parts.append('\n')
        if tag=='a':self.anchor=[d.get('href',''),[]]
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript','template') and self.skip:self.skip-=1;return
        if tag=='title':self.in_title=False
        if tag=='a' and self.anchor:
            self.links.append({'url':self.anchor[0],'title':''.join(self.anchor[1]).strip()});self.anchor=None
        if tag in ('p','div','article','li','h1','h2','h3','tr'):self.parts.append('\n')
    def handle_data(self,data):
        if self.skip:return
        self.parts.append(data)
        if self.in_title:self.title.append(data)
        if self.anchor:self.anchor[1].append(data)

def _normalize(text):return re.sub(r'\n[ \t]*\n+','\n',re.sub(r'[ \t\r\f\v]+',' ',text)).strip()
def _decode(raw,ctype):
    m=re.search(r'charset\s*=\s*["\']?([^;\s"\']+)',ctype,re.I)
    encoding=m.group(1) if m else 'utf-8-sig'
    try:return raw.decode(encoding,'replace')
    except LookupError:return raw.decode('utf-8','replace')

def _extract(raw,headers,url):
    ctype=headers.get('content-type','').lower();mime=ctype.split(';')[0].strip();meta={'content_type':mime,'links':[],'title':''}
    if raw.startswith(b'%PDF-') or mime=='application/pdf':
        child = r"""
import io,json,sys
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(5,5))
    resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
except (ImportError,ValueError,OSError):pass
try:from pypdf import PdfReader
except ImportError:
    print(json.dumps({'error':'PDF_DEPENDENCY_MISSING'}));sys.exit(0)
try:
    reader=PdfReader(io.BytesIO(sys.stdin.buffer.read()))
    if reader.is_encrypted:raise ValueError('PDF_ENCRYPTED')
    pages=len(reader.pages);texts=[];total=0;limit=int(sys.argv[1]);clipped=False
    for page in reader.pages[:40]:
        text=page.extract_text() or ''
        if total+len(text)>limit:text=text[:limit-total];clipped=True
        texts.append(text);total+=len(text)
        if total>=limit:break
    text='\n'.join(texts)
    if not text.strip():raise ValueError('PDF_OCR_REQUIRED')
    print(json.dumps({'text':text,'pages':pages,'pages_read':len(texts),'extraction_truncated':clipped or len(texts)<pages},ensure_ascii=False))
except Exception as e:
    print(json.dumps({'error':str(e) if str(e) in ('PDF_ENCRYPTED','PDF_OCR_REQUIRED') else 'PDF_PARSE_ERROR'}))
"""
        try:
            proc=subprocess.run([sys.executable,'-I','-c',child,str(MAX_BYTES)],input=raw,capture_output=True,timeout=min(TIMEOUT,8),env={'PATH':os.defpath,'LANG':'C.UTF-8'})
        except subprocess.TimeoutExpired:raise FetchFailure('PDF_PARSE_TIMEOUT')
        if proc.returncode:raise FetchFailure('PDF_RESOURCE_OR_PROCESS_ERROR')
        try:doc=json.loads(proc.stdout)
        except ValueError:raise FetchFailure('PDF_PARSE_ERROR')
        if doc.get('error'):raise FetchFailure(doc['error'])
        text=doc.pop('text');meta.update(format='pdf',**doc)
        return text,meta
    text=_decode(raw,ctype)
    if mime.endswith('/json') or mime.endswith('+json'):
        try:text=json.dumps(json.loads(text),ensure_ascii=False,indent=2)
        except ValueError:raise FetchFailure('INVALID_JSON')
        meta['format']='json';return text,meta
    if mime.endswith('/xml') or mime.endswith('+xml') or text.lstrip().startswith('<?xml'):
        if re.search(r'<!DOCTYPE|<!ENTITY',text,re.I):raise FetchFailure('XML_DTD_FORBIDDEN')
        try:root=ET.fromstring(text)
        except ET.ParseError:raise FetchFailure('INVALID_XML')
        meta['format']='xml';return '\n'.join(x.strip() for x in root.itertext() if x.strip()),meta
    if mime in ('text/html','application/xhtml+xml') or re.search(r'<html\b|<!doctype html',text[:4000],re.I):
        p=_Page();p.feed(text);meta.update(format='html',title=''.join(p.title).strip())
        seen=set()
        for link in p.links:
            try:u,_=_url(urllib.parse.urljoin(url,link['url']))
            except Exception:continue
            if u not in seen and len(seen)<100:seen.add(u);meta['links'].append(dict(link,url=u))
        return _normalize(''.join(p.parts)),meta
    if mime and not mime.startswith('text/') and mime not in ('application/javascript','application/x-ndjson'):
        raise FetchFailure('UNSUPPORTED_CONTENT_TYPE')
    if b'\x00' in raw[:4096]:raise FetchFailure('BINARY_CONTENT')
    meta['format']='text';return text,meta

def _redact(value,secrets):
    if isinstance(value,str):
        for secret in secrets:
            if secret:
                for variant in (secret,urllib.parse.quote(secret,safe=''),urllib.parse.quote_plus(secret)):
                    value=value.replace(variant,'[REDACTED]')
        return value
    if isinstance(value,list):return [_redact(x,secrets) for x in value]
    if isinstance(value,dict):return {k:_redact(v,secrets) for k,v in value.items()}
    return value

def _active_secrets(path):
    return [os.getenv(r['auth_env'],'') for r in load_egress(path)['rows'].values() if r.get('auth_env') and r.get('active')]

def fetch(url,lane,*,egress_path='EGRESS.md',db_path=None,route_id=None,mission_id=None,substrate=None,signal_filter=None,opener=None,max_chars=MAX_CHARS,_tool='web.fetch',_private_check=None):
    secrets=_active_secrets(egress_path)
    try:
        from harness.web_fetch_normalize import normalize_url
    except ImportError:
        try:
            from harness.url_normalize import normalize_url
        except ImportError:
            from url_normalize import normalize_url
    raw_in = url if isinstance(url, str) else ('' if url is None else str(url))
    norm, why = normalize_url(raw_in)
    result={'ok':False,'source_url':_safe_url(raw_in,secrets),'lane':lane,'raw':raw_in};grade=None
    if norm is None:
        result.update(status='DENIED', reason='INVALID_URL:'+why, url=None,
                      ok=False, chars=0, truncated=False)
        warning=_log(db_path,route_id,mission_id,substrate,_tool,result['source_url'],0,False,'unverified','DENIED')
        if warning:result['audit_warning']=warning
        return result
    url = norm
    result['url'] = norm
    if norm != raw_in:
        result['normalized'] = True
    result['source_url'] = _safe_url(norm, secrets)
    try:
        max_chars=int(max_chars)
        if not 1<=max_chars<=MAX_BYTES:raise Rejected('invalid max_chars')
        raw,headers,cur,row,trace,used_secrets,status=_request(url,lane,egress_path=egress_path,opener=opener,_private_check=_private_check)
        secrets.extend(used_secrets)
        text,meta=_extract(raw,headers,cur);grade=row['grade']
        if signal_filter:text=signal_filter(text)
        if not isinstance(text,str):raise FetchFailure('INVALID_FILTER_OUTPUT')
        text=_redact(text,secrets);truncated=len(text)>max_chars or meta.get('extraction_truncated',False)
        text=text[:max_chars]+(' [截断]' if truncated else '')
        if not text.strip():raise FetchFailure('EMPTY_CONTENT')
        for link in meta['links']:link['url']=_safe_url(link['url'],secrets)
        result.update(ok=True,status=status,grade=grade,text=text,chars=len(text),truncated=truncated,source_url=_safe_url(cur,secrets),requested_url=_safe_url(url,secrets),fetched_at=int(time.time()),redirects=trace,grade_basis='egress_registration',link_targets_verified=False,matched_rule=row.get('matched_rule'),match_kind=row.get('match_kind'),**meta)
        if opener is not None:result['test_transport']=True
        result=_redact(result,secrets)
    except Rejected as e:result.update(status='DENIED',reason=str(e),matched_rule=getattr(e,'matched_rule',None),match_kind=getattr(e,'match_kind',None))
    except FetchFailure as e:result.update(status=str(e))
    except (TimeoutError,socket.timeout):result.update(status='TIMEOUT')
    except Exception:result.update(status='FETCH_ERROR')
    warning=_log(db_path,route_id,mission_id,substrate,_tool,result['source_url'],result.get('chars',0),result.get('truncated',False),grade,result['status'])
    if warning:result['audit_warning']=warning
    return result

class _SearchPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.results=[];self.active=None;self.snippet=None;self.next_forms=[];self.form=None
    def handle_starttag(self,tag,attrs):
        d=dict(attrs);classes=d.get('class','').split()
        if tag=='a' and any(c in classes for c in ('result__a','result-link')):
            self.active={'url':d.get('href',''),'title':'','snippet':''};self.results.append(self.active)
        if any(c in classes for c in ('result__snippet','result-snippet')) and self.results:self.snippet=(tag,self.results[-1])
        if tag=='form':self.form={'action':d.get('action',''),'fields':{},'next':False}
        if tag=='input' and self.form is not None:
            if d.get('name'):self.form['fields'][d['name']]=d.get('value','')
            if 'next' in d.get('value','').lower():self.form['next']=True
    def handle_data(self,data):
        if self.active is not None:self.active['title']+=data
        if self.snippet is not None:self.snippet[1]['snippet']+=data
        if self.form is not None and 'next' in data.lower():self.form['next']=True
    def handle_endtag(self,tag):
        if tag=='a':self.active=None
        if self.snippet and self.snippet[0]==tag:self.snippet=None
        if tag=='form' and self.form is not None:
            if self.form['next']:self.next_forms.append(self.form)
            self.form=None

def _result_url(href,base):
    u=urllib.parse.urlsplit(urllib.parse.urljoin(base,href))
    if (u.hostname or '').lower() in ('duckduckgo.com','html.duckduckgo.com','lite.duckduckgo.com') and u.path.startswith('/l/'):
        href=urllib.parse.parse_qs(u.query).get('uddg',[''])[0]
    else:href=urllib.parse.urlunsplit(u)
    return _url(href)[0]

def _default_providers(searxng_url):
    raw=os.getenv('WEB_FETCH_SEARCH_PROVIDERS','').strip()
    if raw:
        return tuple(x.strip() for x in raw.split(',') if x.strip())
    out=[]
    if searxng_url:out.append('searxng')
    out.extend(('ddg_html','ddg_lite'))
    return tuple(out)

def _retry_meta(status):
    # retryable=false + retry_after_s>0: do not retry this attempt; a later probe after cooldown is allowed.
    # retryable=false + retry_after_s=0: do not retry this provider/query for this mission.
    if status=='SEARCH_CHALLENGE':
        return False, 3600
    if status in {'SEARCH_ERROR','TIMEOUT','EMPTY_OR_LAYOUT_CHANGED'}:
        return True, 30
    return False, 0

def _parse_search_payload(provider,text,landed):
    parsed=_SearchPage()
    if provider=='searxng':
        doc=json.loads(text)
        if not isinstance(doc,dict) or not isinstance(doc.get('results'),list):raise FetchFailure('INVALID_SEARCH_JSON')
        parsed.results=[{'url':r.get('url',''),'title':str(r.get('title','')),'snippet':str(r.get('content',''))} for r in doc['results'] if isinstance(r,dict)]
        return parsed
    if provider=='github':
        doc=json.loads(text)
        items=doc.get('items') if isinstance(doc,dict) else None
        if not isinstance(items,list):raise FetchFailure('INVALID_SEARCH_JSON')
        parsed.results=[{'url':it.get('html_url',''),'title':str(it.get('full_name') or ''),'snippet':str(it.get('description') or '')} for it in items if isinstance(it,dict)]
        return parsed
    if provider=='wikipedia':
        doc=json.loads(text)
        if not (isinstance(doc,list) and len(doc)>=4):raise FetchFailure('INVALID_SEARCH_JSON')
        titles,descs,urls=doc[1],doc[2],doc[3]
        parsed.results=[{'url':u,'title':str(t),'snippet':str(d)} for t,d,u in zip(titles,descs,urls)]
        return parsed
    if provider=='ddg_api':
        doc=json.loads(text)
        if not isinstance(doc,dict):raise FetchFailure('INVALID_SEARCH_JSON')
        rows=[]
        if doc.get('AbstractURL'):
            rows.append({'url':doc.get('AbstractURL'),'title':str(doc.get('Heading') or ''),'snippet':str(doc.get('AbstractText') or '')})
        for rel in doc.get('RelatedTopics') or []:
            if not isinstance(rel,dict):
                continue
            if rel.get('FirstURL'):
                rows.append({'url':rel.get('FirstURL'),'title':str((rel.get('Text') or '').split(' - ',1)[0]),'snippet':str(rel.get('Text') or '')})
            for t in rel.get('Topics') or []:
                if isinstance(t,dict) and t.get('FirstURL'):
                    rows.append({'url':t.get('FirstURL'),'title':str((t.get('Text') or '').split(' - ',1)[0]),'snippet':str(t.get('Text') or '')})
        parsed.results=rows
        return parsed
    parsed.feed(text)
    return parsed

def search(query,lane,*,n=8,egress_path='EGRESS.md',db_path=None,route_id=None,mission_id=None,substrate=None,opener=None,_private_check=None,max_pages=3,providers=None,domains=None,searxng_url=None):
    n=int(n);max_pages=int(max_pages)
    results=[];attempts=[];seen=set();query=str(query).strip()
    if not query or len(query)>2000 or not 1<=int(n)<=100 or not 1<=int(max_pages)<=5:raise ValueError('query/n/max_pages outside bounds')
    endpoints=dict(SEARCH_ENDPOINTS)
    searxng_env=os.getenv('WEB_FETCH_SEARXNG_URL')
    if searxng_env:
        endpoints['searxng']=_url(searxng_env)[0]
    elif searxng_url and providers is not None:
        # tests / trusted caller with explicit provider list only
        endpoints['searxng']=_url(searxng_url)[0]
    providers=tuple(providers) if providers is not None else _default_providers(searxng_env or searxng_url)
    if not providers or any(p not in endpoints for p in providers):raise ValueError('unknown/unconfigured provider')
    query_sent=query
    if domains:
        normalized=[_host(d) for d in domains]
        if len(normalized)>8 or any(not re.fullmatch(r'[a-z0-9.-]+',d) for d in normalized):raise ValueError('invalid domain filter')
        query_sent+=' ('+' OR '.join('site:'+d for d in normalized)+')'
    for provider in providers:
        base=endpoints[provider]
        if provider=='github':
            params={'q':query_sent,'per_page':str(min(n,10))}
        elif provider=='wikipedia':
            params={'action':'opensearch','search':query_sent,'limit':str(min(n,10)),'namespace':'0','format':'json'}
        elif provider=='ddg_api':
            params={'q':query_sent,'format':'json','no_html':'1','no_redirect':'1'}
        else:
            params={'q':query_sent}
        if provider=='searxng':params.update(format='json',pageno=1)
        cur=base+('&' if '?' in base else '?')+urllib.parse.urlencode(params);visited=set()
        for page in range(int(max_pages)):
            if cur in visited:break
            visited.add(cur)
            try:
                raw,headers,landed,row,trace,secrets,status=_request(cur,lane,egress_path=egress_path,opener=opener,_private_check=_private_check)
                text=_decode(raw,headers.get('content-type',''))
                if re.search(r'anomaly-modal|challenge-form|bots use DuckDuckGo',text,re.I):raise FetchFailure('SEARCH_CHALLENGE')
                parsed=_parse_search_payload(provider,text,landed)
                before=len(results)
                for r in parsed.results:
                    try:url=_result_url(r['url'],landed)
                    except Exception:continue
                    if url in seen:continue
                    kind={'wikipedia':'topic_lookup','ddg_api':'instant_answer','ddg_html':'web_search','ddg_lite':'web_search','github':'repo_search','searxng':'web_search'}.get(provider,'unknown')
                    seen.add(url);results.append(_redact({'title':_normalize(r['title']),'url':_safe_url(url,secrets),'snippet':_normalize(r['snippet'])[:600],'provider':provider,'provider_kind':kind,'page':page+1},secrets))
                    if len(results)>=n:break
                state='ok' if parsed.results else 'EMPTY_OR_LAYOUT_CHANGED'
                attempts.append({'provider':provider,'page':page+1,'status':state,'added':len(results)-before})
                warn=_log(db_path,route_id,mission_id,substrate,'web.search',landed,len(raw),False,'unverified',state)
                if warn:attempts[-1]['audit_warning']=warn
                if len(results)>=n:break
                if provider=='searxng':
                    if not parsed.results:break
                    params['pageno']=page+2;cur=base+('&' if '?' in base else '?')+urllib.parse.urlencode(params);continue
                if not parsed.next_forms:break
                form=parsed.next_forms[0];action=urllib.parse.urljoin(landed,form['action'])
                action,action_host=_url(action)
                if action_host!=urllib.parse.urlsplit(base).hostname:raise Rejected('search pagination changed origin')
                form['fields'].setdefault('q',query_sent)
                # Follow only the supplied next cursor; GET keeps the tool read-only.
                cur=action.split('?')[0]+'?'+urllib.parse.urlencode(form['fields'])
            except Exception as e:
                state='DENIED' if isinstance(e,Rejected) else str(e) if isinstance(e,FetchFailure) else 'SEARCH_ERROR'
                if provider=='github' and isinstance(e,Rejected) and 'auth' in str(e).lower():
                    state='BLOCKED_CONFIG'
                attempts.append({'provider':provider,'page':page+1,'status':state})
                warn=_log(db_path,route_id,mission_id,substrate,'web.search',cur,0,False,'unverified',state)
                if warn:attempts[-1]['audit_warning']=warn
                break
        if len(results)>=n:break
    status=('ok' if len(results)>=n else 'PARTIAL') if results else (attempts[-1]['status'] if attempts else 'EMPTY')
    retryable,retry_after_s=_retry_meta(status)
    return {'ok':bool(results),'status':status,'retryable':retryable,'retry_after_s':retry_after_s,'grade':'unverified','query':query,'results':results,'attempts':attempts,'source_url':_safe_url(endpoints[providers[0]]),'lane':lane,'test_transport':opener is not None}

def search_many(queries,lane,*,n=20,**kwargs):
    queries=list(dict.fromkeys(str(q).strip() for q in queries if str(q).strip()))
    if not 1<=len(queries)<=8 or not 1<=n<=100:raise ValueError('1..8 queries and n=1..100 required')
    groups=[search(q,lane,n=min(n,30),**kwargs) for q in queries];out=[];seen=set()
    # Round-robin preserves coverage from every supplied query.
    for i in range(max((len(g['results']) for g in groups),default=0)):
        for q,g in zip(queries,groups):
            if i<len(g['results']):
                r=g['results'][i]
                if r['url'] not in seen:seen.add(r['url']);out.append(dict(r,query=q))
    if out:
        many_status='ok' if len(out)>=n else 'PARTIAL'
    else:
        st=[g.get('status') for g in groups]
        if any(s=='SEARCH_CHALLENGE' for s in st) and not any(s=='ok' for s in st):
            many_status='SEARCH_CHALLENGE'
        else:
            many_status=next((s for s in st if s and s!='EMPTY'), 'EMPTY')
    retryable,retry_after_s=_retry_meta(many_status)
    return {'ok':bool(out),'status':many_status,'retryable':retryable,'retry_after_s':retry_after_s,'grade':'unverified','results':out[:n],'queries':[{'query':q,'status':g['status'],'attempts':g['attempts'],'retryable':g.get('retryable')} for q,g in zip(queries,groups)]}

def fetch_many(urls,lane,*,workers=4,**kwargs):
    urls=list(dict.fromkeys(urls))
    if len(urls)>50 or not 1<=workers<=8:raise ValueError('at most 50 URLs and 1..8 workers')
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda u:fetch(u,lane,**kwargs),urls))


def _catalog_body(url, body):
    if not isinstance(body, dict):
        raise Rejected('catalog body must be object')
    extra = set(body)
    if url == CATALOG_SEARCH2:
        extra -= {'rows', 'keyword', 'oppStatuses', 'startRecordNum',
                  'eligibilities', 'fundingCategories', 'agencies'}
        if extra:
            raise Rejected('catalog search extra field')
        kw = str(body.get('keyword') or '').strip()
        if not kw or len(kw) > 200:
            raise Rejected('catalog keyword')
        try:
            rows = int(body.get('rows') or 10)
        except (TypeError, ValueError):
            raise Rejected('catalog rows')
        if not 1 <= rows <= 25:
            raise Rejected('catalog rows')
        st = str(body.get('oppStatuses') or 'posted').strip() or 'posted'
        try:
            off = int(body.get('startRecordNum') or 0)
        except (TypeError, ValueError):
            off = 0
        out = {'rows': rows, 'keyword': kw, 'oppStatuses': st}
        if off > 0:
            out['startRecordNum'] = off
        for fld in ('eligibilities', 'fundingCategories', 'agencies'):
            if fld not in body:
                continue
            v = str(body.get(fld) or '').strip()
            if v:
                if len(v) > 200 or not re.match(r'^[A-Za-z0-9|,\-]+$', v):
                    raise Rejected('catalog ' + fld)
                out[fld] = v.replace(',', '|')
            else:
                out[fld] = ''
        return out
    if url == CATALOG_FETCH_OPP:
        extra -= {'opportunityId'}
        if extra:
            raise Rejected('catalog fetch extra field')
        oid = body.get('opportunityId')
        if oid is None or str(oid).strip() == '':
            raise Rejected('opportunityId required')
        return {'opportunityId': str(oid).strip()}
    raise Rejected('catalog post url not allowlisted')


def catalog_json_post(url, body, lane, *, egress_path='EGRESS.md', db_path=None, route_id=None, mission_id=None, substrate=None, opener=None, _private_check=None):
    """Allowlisted JSON POST to grants.gov catalog APIs. Not a generic POST tool."""
    secrets=_active_secrets(egress_path)
    result={'ok':False,'source_url':_safe_url(url,secrets),'lane':lane,'method':'POST'}
    try:
        canon,_=_url(url)
        if canon not in CATALOG_POST_URLS:
            raise Rejected('catalog post url not allowlisted')
        payload=_catalog_body(canon, body)
        raw,headers,cur,row,trace,used_secrets,status=_request(
            canon,lane,egress_path=egress_path,opener=opener,_private_check=_private_check,
            method='POST',data=payload,max_redirects=0)
        secrets.extend(used_secrets)
        ctype=(headers.get('content-type') or '').lower()
        text=_decode(raw, ctype)
        if 'html' in ctype or text.lstrip().lower().startswith('<!doctype') or text.lstrip().lower().startswith('<html'):
            raise FetchFailure('HTML_NOT_JSON')
        try:
            doc=json.loads(text)
        except ValueError:
            raise FetchFailure('INVALID_JSON')
        if not isinstance(doc, dict):
            raise FetchFailure('INVALID_JSON')
        err=doc.get('errorcode') or doc.get('errorCode')
        result.update(ok=True,status=status,grade=row['grade'],json=doc,errorcode=err,
                      source_url=_safe_url(cur,secrets),requested_url=_safe_url(url,secrets),
                      fetched_at=int(time.time()),redirects=trace,chars=len(text),
                      matched_rule=row.get('matched_rule'),match_kind=row.get('match_kind'))
        result=_redact(result,secrets)
    except Rejected as e:result.update(status='DENIED',reason=str(e),matched_rule=getattr(e,'matched_rule',None),match_kind=getattr(e,'match_kind',None))
    except FetchFailure as e:result.update(status=str(e))
    except (TimeoutError,socket.timeout):result.update(status='TIMEOUT')
    except Exception:result.update(status='FETCH_ERROR')
    warning=_log(db_path,route_id,mission_id,substrate,'web.catalog_post',result['source_url'],result.get('chars',0),False,result.get('grade'),result.get('status'))
    if warning:result['audit_warning']=warning
    return result


def normalize_opp_hits(doc, *, source_url, fetched_at, original_query, derived_query=None):
    data = doc.get('data') if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        return {'rows': [], 'hit_count': None, 'pagination_incomplete': True}
    hits = data.get('oppHits') or data.get('oppHitsList') or []
    if not isinstance(hits, list):
        hits = []
    hit_count = data.get('hitCount')
    rows = []
    seen = set()
    for h in hits:
        if not isinstance(h, dict):
            continue
        oid = str(h.get('id') or h.get('opportunityId') or '').strip()
        if not oid or oid in seen:
            continue
        seen.add(oid)
        title = str(h.get('title') or h.get('opportunityTitle') or '').strip()
        agency = str(h.get('agency') or h.get('agencyName') or '').strip()
        posted = str(h.get('openDate') or h.get('postedDate') or '').strip() or 'unknown'
        close = str(h.get('closeDate') or h.get('closeDte') or '').strip() or 'unknown'
        status = str(h.get('oppStatus') or h.get('opportunityStatus') or '').strip() or 'unknown'
        number = str(h.get('number') or h.get('opportunityNumber') or '').strip()
        elig = h.get('eligibilities') or h.get('eligibility') or 'unknown'
        if isinstance(elig, list):
            elig = '; '.join(str(x) for x in elig[:8]) or 'unknown'
        elig = str(elig).strip() or 'unknown'
        human = ''
        for key in ('opportunityLink', 'url', 'detailsUrl'):
            if h.get(key):
                try:
                    human = _url(str(h[key]))[0]
                except Exception:
                    human = ''
                break
        rows.append({
            'opportunity_id': oid,
            'opportunity_number': number or 'unknown',
            'title': title or 'unknown',
            'publisher': agency or 'unknown',
            'published_at': posted,
            'deadline': close,
            'deadline_timezone': 'unknown',
            'eligibility': elig,
            'status': status,
            'source_url': source_url,
            'detail_locator': f'{CATALOG_FETCH_OPP} opportunityId={oid}',
            'human_url': human,
            'fetched_at': fetched_at,
            'original_query': original_query,
            'derived_query': derived_query,
            'qualification': 'needs_verification',
            'qualification_reason': 'list row only; detail not yet fetched',
        })
    incomplete = False
    try:
        if hit_count is not None and int(hit_count) > len(rows):
            incomplete = True
    except (TypeError, ValueError):
        incomplete = True
    return {'rows': rows, 'hit_count': hit_count, 'pagination_incomplete': incomplete, 'page_size': len(rows)}

if __name__=='__main__':
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='template':print(EGRESS_TEMPLATE)
    elif len(sys.argv)>1 and sys.argv[1]=='selftest':
        import subprocess
        sys.exit(subprocess.call([sys.executable,os.path.join(os.path.dirname(__file__),'test_web_fetch.py')]))
    else:print(__doc__)
