"""harness_contract_v1 · 契约 §三 实况探针 + §2.1/§2.2 tool_log + §八 证据等级(2026-09-02,砥)

零新依赖(标准库)。三段各自独立,接线各一两行:

1) 实况行(§三):
     line = live_state_line(providers)          # providers 从能力注册表 + EGRESS.md 派生,见 providers_from_registry()
   注入位置:cloud_gateway_route 请求时,拼在 TOOL_DECLARATION 之后的 system;不落 store。
   每个 provider = {"name": "workstation:8620", "url": "http://127.0.0.1:8620/health", "visible_to_lanes": [...]}
   探针 300ms 超时、60s 缓存;全超时 → 行仍在、标未知,不抛。

2) tool_log(§2.1)+ tool_trace(§2.2):
     log_tool_call(db, route_id, substrate, tool, args, hits, result_chars, truncated, mission_id=None, evidence_grade=None, cost_usd=None)
     trace = tool_trace_line(db, route_id)      # 本轮所有调用压成一条,列表格式,回注本 lane node 时用
   表 tool_log 在 gateway_log.db 新建,不动 route_log。

3) 证据等级(§八):GRADES 阶梯;downgrade_for_citation(grade) = min(grade, secondhand);assert_not_upgraded(old, new) 违者抛。

  python3 harness_contract_v1.py selftest     # 本地 stub 端口,零出网
"""
from __future__ import annotations
import json, os, socket, sqlite3, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

# ---------- §八 证据等级 ----------
GRADES = ["attested", "witnesses_agree", "witness_only", "issuer_claim", "secondhand", "unverified"]   # 高 → 低
_RANK = {g: i for i, g in enumerate(GRADES)}


def grade_rank(g: str) -> int:
    if g not in _RANK: raise ValueError(f"未知证据等级 {g!r};合法:{GRADES}")
    return _RANK[g]


def downgrade_for_citation(g: str) -> str:
    """lane 间引用:等级 = min(原级, secondhand)。"""
    return GRADES[max(grade_rank(g), _RANK["secondhand"])]


def assert_not_upgraded(old: str, new: str) -> None:
    if grade_rank(new) < grade_rank(old):
        raise PermissionError(f"证据等级只降不升:{old} → {new} 拒")


# ---------- §三 实况探针 ----------
_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_LOCK = threading.Lock()
PROBE_TIMEOUT = float(os.environ.get("LIVE_PROBE_TIMEOUT", "0.3"))
PROBE_TTL = float(os.environ.get("LIVE_PROBE_TTL", "60"))


def _probe_one(url: str) -> str:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "grid-probe/1"}), timeout=PROBE_TIMEOUT) as r:
            return "通" if 200 <= r.status < 500 else "断"
    except Exception as e:  # noqa
        return "未起" if isinstance(getattr(e, "reason", None), ConnectionRefusedError) or "refused" in str(e).lower() else "断"


def probe(providers: list[dict], lane: str | None = None, now: float | None = None) -> dict[str, str]:
    """返回 {name: 通/断/未起/未知};按 lane 的 visible_to_lanes 过滤(空列表 = 所有 lane 可见)。带 60s 缓存。"""
    now = now or time.time()
    todo, out = [], {}
    for p in providers:
        vis = p.get("visible_to_lanes") or []
        if lane and vis and lane not in vis: continue
        with _CACHE_LOCK:
            c = _CACHE.get(p["url"])
        if c and now - c[0] < PROBE_TTL:
            out[p["name"]] = c[1]
        else:
            todo.append(p)
    if todo:
        with ThreadPoolExecutor(max_workers=min(8, len(todo))) as ex:
            for p, st in zip(todo, ex.map(lambda q: _probe_one(q["url"]), todo)):
                out[p["name"]] = st
                with _CACHE_LOCK:
                    _CACHE[p["url"]] = (now, st)
    return out


def live_state_line(providers: list[dict], lane: str | None = None) -> str:
    st = probe(providers, lane)
    body = " | ".join(f"{k} {v}" for k, v in st.items()) or "无可探 provider"
    line = f"此刻实况(ts={int(time.time())}):{body}"
    return line[:400]


def providers_from_registry(capabilities: list[dict], egress_rows: list[dict] | None = None) -> list[dict]:
    """能力注册表每条若带 health 字段即成 provider;EGRESS.md 行(domain/grade/lanes)成可达性 provider(HEAD 根路径)。不写死任何端口。"""
    out = []
    for c in capabilities:
        if c.get("health"):
            out.append({"name": c.get("capability_id") or c.get("provider"), "url": c["health"], "visible_to_lanes": c.get("visible_to_lanes") or []})
    for e in egress_rows or []:
        out.append({"name": f"egress:{e['domain']}", "url": f"https://{e['domain']}/", "visible_to_lanes": e.get("lanes") or []})
    return out


# ---------- §2.1 tool_log · §2.2 tool_trace ----------
TOOL_LOG_SCHEMA = """CREATE TABLE IF NOT EXISTS tool_log(
  id INTEGER PRIMARY KEY, route_id TEXT, mission_id TEXT, ts REAL NOT NULL, substrate TEXT, tool TEXT NOT NULL,
  args_json TEXT, hits INTEGER, result_chars INTEGER, truncated INTEGER NOT NULL DEFAULT 0,
  evidence_grade TEXT, cost_usd REAL, status TEXT NOT NULL DEFAULT 'ok', lane TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_tool_log_route ON tool_log(route_id);
CREATE INDEX IF NOT EXISTS ix_tool_log_mission ON tool_log(mission_id);"""


def ensure_tool_log(db_path: str) -> None:
    con = sqlite3.connect(db_path); con.executescript(TOOL_LOG_SCHEMA)
    try:
        cols={r[1] for r in con.execute("PRAGMA table_info(tool_log)")}
        if "lane" not in cols:
            con.execute("ALTER TABLE tool_log ADD COLUMN lane TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    con.commit(); con.close()


def log_tool_call(db_path: str, route_id: str, substrate: str, tool: str, args: dict | None, hits: int | None,
                  result_chars: int, truncated: bool, *, mission_id: str | None = None, evidence_grade: str | None = None,
                  cost_usd: float | None = None, status: str = "ok", lane: str = "") -> int:
    if evidence_grade is not None: grade_rank(evidence_grade)
    a = json.dumps(args or {}, ensure_ascii=False)[:300]
    con = sqlite3.connect(db_path); con.executescript(TOOL_LOG_SCHEMA)
    try:
        cols={r[1] for r in con.execute("PRAGMA table_info(tool_log)")}
        has_lane = "lane" in cols
    except Exception:
        has_lane = False
    if has_lane:
        cur = con.execute("INSERT INTO tool_log(route_id,mission_id,ts,substrate,tool,args_json,hits,result_chars,truncated,evidence_grade,cost_usd,status,lane)"
                          " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (route_id, mission_id, time.time(), substrate, tool, a, hits, int(result_chars), 1 if truncated else 0, evidence_grade, cost_usd, status, lane or substrate or ""))
    else:
        cur = con.execute("INSERT INTO tool_log(route_id,mission_id,ts,substrate,tool,args_json,hits,result_chars,truncated,evidence_grade,cost_usd,status)"
                          " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (route_id, mission_id, time.time(), substrate, tool, a, hits, int(result_chars), 1 if truncated else 0, evidence_grade, cost_usd, status))
    con.commit(); rid = cur.lastrowid; con.close(); return int(rid)


def tool_trace_line(db_path: str, route_id: str) -> str:
    """本轮所有工具调用压成一条(列表格式,按顺序,不丢链)。回注本 lane node 时作 type=tool_trace 的 body。"""
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT tool, args_json, hits, result_chars, truncated, evidence_grade, status FROM tool_log WHERE route_id=? ORDER BY id", (route_id,)).fetchall()
    con.close()
    by: dict[str, list[str]] = {}
    for tool, a, hits, chars, trunc, grade, status in rows:
        try:
            args = json.loads(a or "{}")
        except Exception:
            args = {}
        key = ",".join(f"{k}={str(v)[:24]}" for k, v in list(args.items())[:2])
        item = f"({key},hits={hits},chars={chars}{',[截断]' if trunc else ''}{',' + grade if grade else ''}{',' + status if status != 'ok' else ''})"
        by.setdefault(tool, []).append(item)
    return " | ".join(f"{t}: [{', '.join(v)}]" for t, v in by.items()) or "(本轮未调工具)"


# ---------- 自测 ----------

def _stub_server(status: int):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if status == "slow": time.sleep(1.0)
            try:
                self.send_response(200 if status == "slow" else status); self.end_headers(); self.wfile.write(b"{}")
            except (BrokenPipeError, ConnectionResetError):
                pass   # 客户端已按 300ms 超时断开,预期
        def log_message(self, *a): pass
    s = HTTPServer(("127.0.0.1", 0), H); th = threading.Thread(target=s.serve_forever, daemon=True); th.start()
    return s, s.server_address[1]


def selftest() -> int:
    import tempfile
    fails: list[str] = []; must = lambda c, m: (None if c else fails.append(m))
    # 等级
    must(downgrade_for_citation("attested") == "secondhand" and downgrade_for_citation("unverified") == "unverified", "1 引用降级")
    try:
        assert_not_upgraded("secondhand", "attested"); must(False, "2 升级未拒")
    except PermissionError:
        pass
    assert_not_upgraded("attested", "secondhand")
    try:
        grade_rank("solid"); must(False, "3 未知等级未拒")
    except ValueError:
        pass
    # 探针
    ok_s, p_ok = _stub_server(200); bad_s, p_bad = _stub_server(503); slow_s, p_slow = _stub_server("slow")
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0)); p_dead = sk.getsockname()[1]      # 释放后无人听 → 未起
    provs = [{"name": "ok", "url": f"http://127.0.0.1:{p_ok}/health", "visible_to_lanes": []},
             {"name": "bad", "url": f"http://127.0.0.1:{p_bad}/health", "visible_to_lanes": ["glm52"]},
             {"name": "slow", "url": f"http://127.0.0.1:{p_slow}/health", "visible_to_lanes": []},
             {"name": "dead", "url": f"http://127.0.0.1:{p_dead}/health", "visible_to_lanes": ["rwa"]}]
    t0 = time.time(); st = probe(provs); dt = time.time() - t0
    must(st["ok"] == "通" and st["bad"] == "断" and st["slow"] == "断" and st["dead"] == "未起", f"4 探针判定 {st}")
    must(dt < 1.0, f"5 并发+超时:总耗时 {dt:.2f}s 应 <1s(slow 1s 被 300ms 截)")
    st2 = probe(provs, lane="glm52"); must(set(st2) == {"ok", "bad", "slow"}, f"6 lane 过滤 {set(st2)}")
    ok_s.shutdown(); st3 = probe(provs); must(st3["ok"] == "通", "7 60s 缓存:刚关的仍读缓存")
    line = live_state_line(provs); must(line.startswith("此刻实况(ts=") and "ok 通" in line and len(line) <= 400, f"8 实况行 {line[:60]}")
    provs2 = providers_from_registry([{"capability_id": "x.y", "health": "http://127.0.0.1:1/h", "visible_to_lanes": ["a"]}, {"capability_id": "no.health"}],
                                     [{"domain": "efts.sec.gov", "grade": "attested", "lanes": ["research"]}])
    must([p["name"] for p in provs2] == ["x.y", "egress:efts.sec.gov"], "9 注册表派生")
    bad_s.shutdown(); slow_s.shutdown()
    # tool_log / trace
    db = os.path.join(tempfile.mkdtemp(), "g.db"); ensure_tool_log(db)
    log_tool_call(db, "r1", "glm52", "store.search", {"query": "option workflow", "limit": 5}, 2, 1800, False, mission_id="m1", evidence_grade="witness_only")
    log_tool_call(db, "r1", "glm52", "store.search", {"query": "8620"}, 0, 0, False, mission_id="m1")
    log_tool_call(db, "r1", "glm52", "store.get", {"id": "318"}, 1, 6000, True, mission_id="m1", evidence_grade="secondhand")
    log_tool_call(db, "r1", "glm52", "web.fetch", {"url": "https://x"}, None, 0, False, status="DENIED")
    tr = tool_trace_line(db, "r1")
    must(tr.count("store.search") == 1 and "hits=2" in tr and "hits=0" in tr and "[截断]" in tr and "DENIED" in tr, f"10 trace 列表格式 {tr}")
    must(tool_trace_line(db, "nope") == "(本轮未调工具)", "11 空轮")
    try:
        log_tool_call(db, "r2", "glm52", "t", {}, 0, 0, False, evidence_grade="solid"); must(False, "12 非法等级未拒")
    except ValueError:
        pass
    n = sqlite3.connect(db).execute("SELECT COUNT(*) FROM tool_log WHERE mission_id='m1'").fetchone()[0]; must(n == 3, "13 mission_id 串")
    if fails:
        print("SELFTEST FAIL"); [print(" -", f) for f in fails]; return 1
    print("SELFTEST PASS 13/13(等级只降不升 · 探针通/断/未起/超时并发 · lane 过滤 · 缓存 · 实况行 · 注册表派生 · tool_log · trace 列表 · mission 串)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(selftest() if len(sys.argv) > 1 and sys.argv[1] == "selftest" else 2)
