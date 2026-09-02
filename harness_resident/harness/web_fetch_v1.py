"""web_fetch_v1 · 契约 §七 P3a:一个只读 fetch + 一张登记表(2026-09-02,砥)

EGRESS.md(仓根,与 PORTS.md 并列)每行一个源:
  | domain | 用途 | 只读 | 鉴权(env 名或 none) | 速率/min | grade | 拍板日期 | lanes |
未登记域名一律拒(DENIED 进 tool_log);grade 缺失或非法 → 该行不生效(同样拒);只 GET;
回执 ≤ MAX_CHARS 截断带 [截断];鉴权只从 env 读、不进回执;回执经 signal_filter 回调(SIGNAL_RE,调用方传入);
lane 级每轮次数预算由调用方在 executor 里数,这里不数。

  fetch(url, lane, *, egress_path="EGRESS.md", db_path=None, route_id=None, mission_id=None, signal_filter=None) -> dict
     → {"ok":True,"grade":...,"chars":n,"truncated":bool,"text":...,"source_url":url,"fetched_at":ts}
     或 {"ok":False,"status":"DENIED"|"HTTP 5xx"|"TIMEOUT",...}(不编内容)

  python3 web_fetch_v1.py selftest        # 本地 stub 域名,零出网
"""
from __future__ import annotations
import json, os, re, time, urllib.error, urllib.parse, urllib.request

MAX_CHARS = int(os.environ.get("WEB_FETCH_MAX_CHARS", "6000"))
TIMEOUT = float(os.environ.get("WEB_FETCH_TIMEOUT", "15"))
GRADES = {"attested", "witnesses_agree", "witness_only", "issuer_claim", "secondhand", "unverified"}

EGRESS_TEMPLATE = """# EGRESS.md · 出网登记表(bind-before-register 同款:未登记一律拒)

| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |
|---|---|---|---|---|---|---|---|
| efts.sec.gov | EDGAR 全文检索 | yes | none | 10 | attested | | research,rwa |
| data.sec.gov | EDGAR 提交 JSON(需 User-Agent 含邮箱:SEC_UA) | yes | SEC_UA | 10 | attested | | research,rwa |
| export.arxiv.org | arXiv API | yes | none | 20 | issuer_claim | | research |
| www.grants.gov | grants.gov 检索 | yes | none | 20 | attested | | scout |
| api.sam.gov | SAM.gov 机会 | yes | SAM_API_KEY | 10 | attested | | scout |
| api.github.com | GitHub API | yes | GITHUB_TOKEN | 30 | issuer_claim | | maintainer,research |

拍板列为空 = 未生效(fetch 一律拒)。Lyra 在拍板列填日期即生效。grade 按 rwa v7 阶梯;lanes 空 = 所有 lane。
"""


def load_egress(path: str = "EGRESS.md") -> dict[str, dict]:
    """解析登记表;拍板列为空、grade 非法、只读非 yes 的行不生效。"""
    rows: dict[str, dict] = {}
    if not os.path.exists(path): return rows
    for line in open(path, encoding="utf-8"):
        if not line.startswith("|") or line.startswith("|---") or "domain" in line[:12]: continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8: continue
        domain, purpose, ro, auth, rate, grade, approved, lanes = cells[:8]
        if not approved or grade not in GRADES or ro.lower() != "yes": continue
        rows[domain.lower()] = {"domain": domain.lower(), "purpose": purpose, "auth_env": None if auth.lower() in ("", "none") else auth,
                                "rate": int(rate or 0), "grade": grade, "approved": approved, "lanes": [x.strip() for x in lanes.split(",") if x.strip()]}
    return rows


def _deny(reason: str, url: str, lane: str, db_path, route_id, mission_id, substrate) -> dict:
    _log(db_path, route_id, mission_id, substrate, url, 0, False, None, "DENIED")
    return {"ok": False, "status": "DENIED", "reason": reason, "source_url": url, "lane": lane}


def _log(db_path, route_id, mission_id, substrate, url, chars, truncated, grade, status):
    if not db_path: return
    try:
        import harness_contract_v1 as HC
        HC.log_tool_call(db_path, route_id or "", substrate or "", "web.fetch", {"url_host": urllib.parse.urlparse(url).netloc}, None, chars, truncated,
                         mission_id=mission_id, evidence_grade=grade, status=status)
    except Exception:
        pass


def fetch(url: str, lane: str, *, egress_path: str = "EGRESS.md", db_path: str | None = None, route_id: str | None = None,
          mission_id: str | None = None, substrate: str | None = None, signal_filter=None, opener=None, max_chars: int = MAX_CHARS) -> dict:
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" and not u.netloc.startswith("127.0.0.1"):
        return _deny("只允许 https", url, lane, db_path, route_id, mission_id, substrate)
    reg = load_egress(egress_path)
    row = reg.get(u.netloc.lower())
    if not row:
        return _deny("域名未登记或未拍板/等级缺失", url, lane, db_path, route_id, mission_id, substrate)
    if row["lanes"] and lane not in row["lanes"]:
        return _deny(f"lane {lane} 不在该源可用 lane", url, lane, db_path, route_id, mission_id, substrate)
    headers = {"User-Agent": "grid-fetch/1"}
    if row["auth_env"]:
        val = os.environ.get(row["auth_env"])
        if not val:
            return _deny(f"鉴权 env {row['auth_env']} 未设", url, lane, db_path, route_id, mission_id, substrate)
        if row["auth_env"] == "SEC_UA": headers["User-Agent"] = val
        else: headers["Authorization"] = f"Bearer {val}"
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as r:
            raw = r.read(max_chars * 4 + 1)
            status = getattr(r, "status", 200)
    except urllib.error.HTTPError as e:
        _log(db_path, route_id, mission_id, substrate, url, 0, False, row["grade"], f"HTTP {e.code}")
        return {"ok": False, "status": f"HTTP {e.code}", "source_url": url}
    except Exception as e:  # noqa
        st = "TIMEOUT" if "timed out" in str(e).lower() else type(e).__name__
        _log(db_path, route_id, mission_id, substrate, url, 0, False, row["grade"], st)
        return {"ok": False, "status": st, "source_url": url}
    text = raw.decode("utf-8", "replace")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text) if "<html" in text[:2000].lower() else text
    text = re.sub(r"[ \t]+", " ", text).strip()
    truncated = len(text) > max_chars
    if truncated: text = text[:max_chars] + " [截断]"
    if signal_filter:
        text = signal_filter(text)
    if row["auth_env"] and os.environ.get(row["auth_env"], "\x00") in text:
        text = "[回执含鉴权值,已拦]"; truncated = False
    _log(db_path, route_id, mission_id, substrate, url, len(text), truncated, row["grade"], "ok")
    return {"ok": True, "status": status, "grade": row["grade"], "chars": len(text), "truncated": truncated, "text": text,
            "source_url": url, "fetched_at": int(time.time()), "lane": lane}


# ---------- 自测 ----------

def selftest() -> int:
    import tempfile, io
    t = tempfile.mkdtemp(); eg = os.path.join(t, "EGRESS.md"); db = os.path.join(t, "g.db")
    open(eg, "w").write("""| domain | 用途 | 只读 | 鉴权 env | 速率/min | grade | 拍板 | lanes |
|---|---|---|---|---|---|---|---|
| ok.test | 测 | yes | none | 10 | attested | 2026-09-02 | research |
| nograde.test | 测 | yes | none | 10 | | 2026-09-02 | |
| unapproved.test | 测 | yes | none | 10 | attested | | |
| auth.test | 测 | yes | X_TOKEN | 10 | issuer_claim | 2026-09-02 | |
| write.test | 测 | no | none | 10 | attested | 2026-09-02 | |
""")
    class R:
        def __init__(s, body, status=200): s.b = body; s.status = status
        def read(s, n=-1): return s.b if isinstance(s.b, bytes) else s.b.encode()
        def __enter__(s): return s
        def __exit__(s, *a): return False
    def opener(req, timeout):
        host = urllib.parse.urlparse(req.full_url).netloc
        if host == "ok.test":
            if req.full_url.endswith("/big"): return R("x" * 20000)
            if req.full_url.endswith("/500"):
                raise urllib.error.HTTPError(req.full_url, 503, "svc", {}, io.BytesIO(b""))
            return R("<html><script>bad()</script><p>hello  world</p></html>")
        if host == "auth.test":
            return R("token is " + req.headers.get("Authorization", "").replace("Bearer ", "") + " ok")
        return R("should not reach")
    fails = []; must = lambda c, m: (None if c else fails.append(m))
    reg = load_egress(eg); must(set(reg) == {"ok.test", "auth.test"}, f"1 登记表解析:无拍板/无等级/非只读行应不生效 {set(reg)}")
    r = fetch("https://ok.test/p", "research", egress_path=eg, db_path=db, route_id="r1", opener=opener)
    must(r["ok"] and r["grade"] == "attested" and r["text"] == "hello world", f"2 正常 fetch 去标签 {r}")
    must(fetch("https://ok.test/p", "scout", egress_path=eg, db_path=db, opener=opener)["status"] == "DENIED", "3 lane 不在白名单 → DENIED")
    must(fetch("https://nope.test/", "research", egress_path=eg, db_path=db, opener=opener)["status"] == "DENIED", "4 未登记 → DENIED")
    must(fetch("https://nograde.test/", "research", egress_path=eg, db_path=db, opener=opener)["status"] == "DENIED", "5 无等级 → DENIED")
    must(fetch("https://unapproved.test/", "research", egress_path=eg, db_path=db, opener=opener)["status"] == "DENIED", "6 未拍板 → DENIED")
    must(fetch("http://ok.test/p", "research", egress_path=eg, db_path=db, opener=opener)["status"] == "DENIED", "7 http → DENIED")
    big = fetch("https://ok.test/big", "research", egress_path=eg, db_path=db, opener=opener)
    must(big["truncated"] and big["text"].endswith("[截断]") and big["chars"] <= MAX_CHARS + 10, "8 截断")
    must(fetch("https://ok.test/500", "research", egress_path=eg, db_path=db, opener=opener)["status"] == "HTTP 503", "9 5xx 不编内容")
    os.environ.pop("X_TOKEN", None)
    must(fetch("https://auth.test/", "research", egress_path=eg, db_path=db, opener=opener)["status"] == "DENIED", "10 鉴权 env 缺 → DENIED")
    os.environ["X_TOKEN"] = "s3cr3t"
    ra = fetch("https://auth.test/", "research", egress_path=eg, db_path=db, opener=opener)
    must(ra["ok"] and "s3cr3t" not in ra["text"], f"11 回执含鉴权值须拦 {ra.get('text')}")
    filt = lambda s: s.replace("hello", "[SIGNAL]")
    must(fetch("https://ok.test/p", "research", egress_path=eg, db_path=db, opener=opener, signal_filter=filt)["text"].startswith("[SIGNAL]"), "12 signal_filter 生效")
    import sqlite3
    n_denied = sqlite3.connect(db).execute("SELECT COUNT(*) FROM tool_log WHERE tool='web.fetch' AND status='DENIED'").fetchone()[0]
    must(n_denied >= 5, f"13 DENIED 进 tool_log {n_denied}")
    if fails:
        print("SELFTEST FAIL"); [print(" -", f) for f in fails]; return 1
    print("SELFTEST PASS 13/13(登记表解析 · 去标签 · lane/未登记/无等级/未拍板/http 五种 DENIED · 截断 · 5xx · 鉴权缺/泄 · signal_filter · tool_log)")
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selftest": sys.exit(selftest())
    if len(sys.argv) > 1 and sys.argv[1] == "template": print(EGRESS_TEMPLATE); sys.exit(0)
    print(__doc__); sys.exit(2)
