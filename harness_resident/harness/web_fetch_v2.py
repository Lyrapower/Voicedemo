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
GRADES={'attested','witnesses_agree','witness_only','issuer_claim','secondhand','unverified'}
SEARCH_HOST='html.duckduckgo.com'
SEARCH_ENDPOINTS={'ddg_html':'https://html.duckduckgo.com/html/','ddg_lite':'https://lite.duckduckgo.com/lite/'}
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

class Rejected(Exception): pass
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

def load_egress(path='EGRESS.md'):
    out={'rows':{},'star':None,'deny':[],'warnings':[]};deny=False
    if not os.path.exists(path):return out
    with open(path,encoding='utf-8') as f:
        for line in f:
            s=line.strip()
            if s.lower()=='[deny]':deny=True;continue
            if deny:
                if s and not s.startswith(('#','|')):out['deny'].append(_host(s.lstrip('.')))
                continue
            if not s.startswith('|'):continue
            cells=[x.strip() for x in s.strip('|').split('|')]
            if len(cells)<8 or cells[0] in ('domain','---'):continue
            domain,purpose,ro,auth,rate,grade,approved,lanes=cells[:8]
            if not approved or grade not in GRADES or ro.lower()!='yes':continue
            try:
                rate=int(rate)
                if rate<1:raise ValueError()
                domain=domain.lower().rstrip('.')
                domain=domain if domain=='*' else ('*.'+_host(domain[2:]) if domain.startswith('*.') else _host(domain))
            except (ValueError,UnicodeError):out['warnings'].append('invalid approved registration');continue
            row={'domain':domain,'purpose':purpose,'auth_env':None if auth.lower() in ('none','') else auth,'rate':rate,'grade':grade,'approved':approved,'lanes':[x.strip() for x in lanes.split(',') if x.strip()]}
            if domain=='*':row.update(grade='unverified',auth_env=None);out['star']=row
            else:out['rows'][domain]=row
    return out

def _resolve_row(reg,host,lane):
    h=_host(host)
    for suffix in reg['deny']:
        if h==suffix or h.endswith('.'+suffix):return None,'domain denied'
    row=reg['rows'].get(h)
    if row is None:
        matches=[(len(k),v) for k,v in reg['rows'].items() if k.startswith('*.') and h.endswith(k[1:])]
        row=max(matches,key=lambda x:x[0])[1] if matches else reg['star']
    if not row:return None,'domain not approved (no active wildcard)'
    if row['lanes'] and lane not in row['lanes']:return None,'lane not allowed for this source'
    return row,None

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

def _log(db_path,route_id,mission_id,substrate,tool,url,chars,truncated,grade,status):
    if not db_path:return None
    try:
        try:
            from . import harness_contract_v1 as HC
        except ImportError:
            import harness_contract_v1 as HC
        HC.log_tool_call(db_path,route_id or '',substrate or '',tool,{'url_host':urllib.parse.urlsplit(url).hostname},None,chars,truncated,mission_id=mission_id,evidence_grade=grade,status=status)
        return None
    except Exception:return 'tool_log_failed'

def _request(url,lane,*,egress_path,opener=None,_private_check=None):
    reg=load_egress(egress_path);cur=url;trace=[];secrets=[];deadline=time.monotonic()+TIMEOUT
    # Legacy injection seam is for tests only; it cannot disable production DNS checks.
    if _private_check is not None and opener is None:raise Rejected('private-check override requires test opener')
    for hop in range(MAX_REDIRECTS+1):
        cur,host=_url(cur);row,why=_resolve_row(reg,host,lane)
        if not row:raise Rejected(why)
        if opener is not None and _private_check is not None:
            if _private_check(host):raise Rejected('non-public address forbidden')
            ips=[]
        else:ips=_public_ips(host)
        headers={'User-Agent':'grid-fetch/3','Accept':'text/html,application/json,application/xml,application/pdf,text/plain,*/*;q=0.5','Accept-Encoding':'gzip'}
        if row['auth_env']:
            val=os.getenv(row['auth_env'])
            if not val:raise Rejected('required auth environment missing')
            if '\r' in val or '\n' in val:raise Rejected('invalid auth header')
            secrets.append(val);headers['User-Agent' if row['auth_env']=='SEC_UA' else 'Authorization']=val if row['auth_env']=='SEC_UA' else 'Bearer '+val
        if not _rate(egress_path,row,host):raise FetchFailure('RATE_LIMITED')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise FetchFailure('TIMEOUT')
        conn=None;response=None
        try:
            if opener is not None:
                try:response=opener(urllib.request.Request(cur,headers=headers,method='GET'),timeout=remaining)
                except urllib.error.HTTPError as e:response=e
                landed=getattr(response,'geturl',lambda:cur)() or cur
                if _url(landed)[0]!=cur:raise Rejected('test opener silently followed redirect')
            else:
                conn=_PinnedHTTPS(host,ips,remaining);u=urllib.parse.urlsplit(cur)
                conn.request('GET',u.path+('?' + u.query if u.query else ''),headers=headers);response=conn.getresponse()
            status=getattr(response,'status',None) or getattr(response,'code',200)
            rh={k.lower():v for k,v in response.headers.items()}
            trace.append({'url':_safe_url(cur,secrets),'status':status,'grade':row['grade']})
            if status in (301,302,303,307,308):
                if hop==MAX_REDIRECTS or not rh.get('location'):raise FetchFailure('REDIRECT_LIMIT')
                cur=urllib.parse.urljoin(cur,rh['location']);continue
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

def fetch(url,lane,*,egress_path='EGRESS.md',db_path=None,route_id=None,mission_id=None,substrate=None,signal_filter=None,opener=None,max_chars=MAX_CHARS,_tool='web.fetch',_private_check=None):
    secrets=[os.getenv(r['auth_env'],'') for r in load_egress(egress_path)['rows'].values() if r['auth_env']]
    result={'ok':False,'source_url':_safe_url(url,secrets),'lane':lane};grade=None
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
        result.update(ok=True,status=status,grade=grade,text=text,chars=len(text),truncated=truncated,source_url=_safe_url(cur,secrets),requested_url=_safe_url(url,secrets),fetched_at=int(time.time()),redirects=trace,grade_basis='egress_registration',link_targets_verified=False,**meta)
        if opener is not None:result['test_transport']=True
        result=_redact(result,secrets)
    except Rejected as e:result.update(status='DENIED',reason=str(e))
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

def search(query,lane,*,n=8,egress_path='EGRESS.md',db_path=None,route_id=None,mission_id=None,substrate=None,opener=None,_private_check=None,max_pages=3,providers=None,domains=None,searxng_url=None):
    n=int(n);max_pages=int(max_pages)
    results=[];attempts=[];seen=set();query=str(query).strip()
    if not query or len(query)>2000 or not 1<=int(n)<=100 or not 1<=int(max_pages)<=5:raise ValueError('query/n/max_pages outside bounds')
    endpoints=dict(SEARCH_ENDPOINTS)
    searxng_url=searxng_url or os.getenv('WEB_FETCH_SEARXNG_URL')
    if searxng_url:endpoints['searxng']=_url(searxng_url)[0]
    providers=tuple(providers) if providers is not None else (('searxng',) if searxng_url else ())+('ddg_html','ddg_lite')
    if not providers or any(p not in endpoints for p in providers):raise ValueError('unknown/unconfigured provider')
    query_sent=query
    if domains:
        normalized=[_host(d) for d in domains]
        if len(normalized)>8 or any(not re.fullmatch(r'[a-z0-9.-]+',d) for d in normalized):raise ValueError('invalid domain filter')
        query_sent+=' ('+' OR '.join('site:'+d for d in normalized)+')'
    for provider in providers:
        base=endpoints[provider]
        params={'q':query_sent}
        if provider=='searxng':params.update(format='json',pageno=1)
        cur=base+('&' if '?' in base else '?')+urllib.parse.urlencode(params);visited=set()
        for page in range(int(max_pages)):
            if cur in visited:break
            visited.add(cur)
            try:
                raw,headers,landed,row,trace,secrets,status=_request(cur,lane,egress_path=egress_path,opener=opener,_private_check=_private_check)
                text=_decode(raw,headers.get('content-type',''));parsed=_SearchPage()
                if provider=='searxng':
                    doc=json.loads(text)
                    if not isinstance(doc,dict) or not isinstance(doc.get('results'),list):raise FetchFailure('INVALID_SEARCH_JSON')
                    parsed.results=[{'url':r.get('url',''),'title':str(r.get('title','')),'snippet':str(r.get('content',''))} for r in doc['results'] if isinstance(r,dict)]
                else:parsed.feed(text)
                if re.search(r'anomaly-modal|challenge-form|bots use DuckDuckGo',text,re.I):raise FetchFailure('SEARCH_CHALLENGE')
                before=len(results)
                for r in parsed.results:
                    try:url=_result_url(r['url'],landed)
                    except Exception:continue
                    if url in seen:continue
                    seen.add(url);results.append(_redact({'title':_normalize(r['title']),'url':_safe_url(url,secrets),'snippet':_normalize(r['snippet'])[:600],'provider':provider,'page':page+1},secrets))
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
                attempts.append({'provider':provider,'page':page+1,'status':state})
                warn=_log(db_path,route_id,mission_id,substrate,'web.search',cur,0,False,'unverified',state)
                if warn:attempts[-1]['audit_warning']=warn
                break
        if len(results)>=n:break
    return {'ok':bool(results),'status':('ok' if len(results)>=n else 'PARTIAL') if results else (attempts[-1]['status'] if attempts else 'EMPTY'),'grade':'unverified','query':query,'results':results,'attempts':attempts,'source_url':_safe_url(endpoints[providers[0]]),'lane':lane,'test_transport':opener is not None}

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
    return {'ok':bool(out),'status':'ok' if len(out)>=n else 'PARTIAL' if out else 'EMPTY','grade':'unverified','results':out[:n],'queries':[{'query':q,'status':g['status'],'attempts':g['attempts']} for q,g in zip(queries,groups)]}

def fetch_many(urls,lane,*,workers=4,**kwargs):
    urls=list(dict.fromkeys(urls))
    if len(urls)>50 or not 1<=workers<=8:raise ValueError('at most 50 URLs and 1..8 workers')
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda u:fetch(u,lane,**kwargs),urls))

if __name__=='__main__':
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='template':print(EGRESS_TEMPLATE)
    elif len(sys.argv)>1 and sys.argv[1]=='selftest':
        import subprocess
        sys.exit(subprocess.call([sys.executable,os.path.join(os.path.dirname(__file__),'test_web_fetch.py')]))
    else:print(__doc__)
