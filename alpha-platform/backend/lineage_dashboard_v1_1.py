"""lineage_dashboard v1.1 · 因子闭环仪表(2026-09-02,砥;v1.1 按 ALPHA PLATFORM 现有视觉:深底 / 琥珀 / 等宽数字 / 圆角卡)

只读。吃 factor_lineage.db,不吃别的。标准库 http.server,只绑 127.0.0.1。
端口不写死:--port 必填,bind 前先登记 PORTS.md(bind-before-register)。

  python3 lineage_dashboard_v1.py --db state/factor_lineage.db --port <已登记端口>
  python3 lineage_dashboard_v1.py --demo --port <端口>      # 合成数据,只为看仪表长什么样

页面:
  预算槽  12 格,live 因子填几格;这是环的硬闸,放最上面。
  榜      n_obs ≥ MIN_N 的因子按 t 排;每行 IC / t / 命中率 / 天数 / 结算口径 / 判定 + 20 日滚动 IC 小线。
  死枝    rejected 因子与原因。
  链      点任一因子:祖先 → 自身 → 沙箱 → 每次评估,按时间。
空态不是装饰:榜空显示"没有 n_obs ≥ MIN_N 的评估",并给出下一条命令。
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HTML = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>因子闭环 · lineage</title>
<style>
:root{--bg:#0B0F17;--card:#121826;--card2:#0F141F;--line:#1F2937;--ink:#E5E7EB;--ink2:#8B95A5;--amber:#E5A93C;--green:#3DD68C;--red:#F0627A;--purple:#A78BFA;--slot:#1A2130}
*{box-sizing:border-box}html{font:15px/1.5 -apple-system,"SF Pro Text","Segoe UI",system-ui,sans-serif;color:var(--ink);background:var(--bg)}
body{margin:0;padding:22px 18px 60px;max-width:1080px}
.hd{display:flex;align-items:baseline;gap:14px;margin:0 0 4px}.hd b{font-weight:700;letter-spacing:.08em;font-size:17px}.hd span{color:var(--ink2);font-size:14px}
.sub{color:var(--ink2);font-size:13px;margin:0 0 20px}
.mono{font-family:"SF Mono",Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:0 0 16px}
.card h2{font-size:15px;font-weight:600;margin:0 0 12px;color:var(--ink)}.card h2 small{color:var(--ink2);font-weight:400;margin-left:8px;font-size:13px}
.slots{display:flex;gap:6px;margin:0 0 8px}.slot{flex:1;height:36px;background:var(--slot);border-radius:6px;position:relative;border:1px solid var(--line)}
.slot.on{background:var(--amber);border-color:var(--amber)}.slot span{position:absolute;left:6px;bottom:5px;font-size:11px;color:#0B0F17;font-weight:600;white-space:nowrap;overflow:hidden;max-width:calc(100% - 8px)}
.meter{display:flex;justify-content:space-between;color:var(--ink2);font-size:13px}.meter b{color:var(--red);font-weight:600}
.cols{display:grid;grid-template-columns:1.6fr 1fr;gap:16px}@media(max-width:820px){.cols{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse}th{text-align:left;font-weight:500;color:var(--ink2);font-size:12px;padding:0 8px 8px 0;border-bottom:1px solid var(--line)}
td{padding:9px 8px 9px 0;border-bottom:1px solid var(--line);vertical-align:middle;font-size:14px}tr.row{cursor:pointer}tr.row:hover td{background:var(--card2)}
td.num{font-family:"SF Mono",Menlo,monospace;font-variant-numeric:tabular-nums}
.v-keep{color:var(--green)}.v-reject{color:var(--red)}.v-watch{color:var(--amber)}.v-insufficient{color:var(--ink2)}
svg.spark{width:90px;height:22px;display:block}.spark path{fill:none;stroke:var(--amber);stroke-width:1.4}.spark line{stroke:var(--line);stroke-width:1}
.dead li{list-style:none;margin:0 0 10px;padding:8px 10px;border-radius:8px;background:var(--card2);border-left:3px solid var(--red)}.dead ul{padding:0;margin:0}.dead b{font-weight:600}.dead small{color:var(--ink2);display:block;margin-top:2px}
.empty{color:var(--ink2);padding:6px 0;font-size:14px}.empty code{background:var(--slot);padding:2px 6px;border-radius:4px;font-size:13px;font-family:"SF Mono",Menlo,monospace}
#chain{margin-top:4px}
.step{display:grid;grid-template-columns:110px 1fr;gap:12px;padding:9px 0;border-bottom:1px solid var(--line)}.step .t{color:var(--ink2);font-size:13px;font-family:"SF Mono",Menlo,monospace}
.step.anc{opacity:.7}.tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--line);color:var(--ink2);margin-left:6px}
.tag.live{border-color:var(--amber);color:var(--amber)}.tag.rejected{border-color:var(--red);color:var(--red)}.tag.sandbox_ok{border-color:var(--green);color:var(--green)}
a.close{float:right;color:var(--ink2);text-decoration:none;font-size:13px}
</style></head><body>
<div class="hd"><b>ALPHA PLATFORM</b><span>因子闭环 · lineage</span></div><p class="sub" id="sub">读取中</p>
<div class="card"><h2>预算槽<small>live 因子占位,第 13 个晋级即拒</small></h2><div class="slots" id="slots"></div><div class="meter"><span id="budget"></span><span id="meta"></span></div></div>
<div class="cols">
 <div class="card"><h2>榜<small>n ≥ <span id="minn"></span> 天 · 按 t</small></h2><div id="board"></div></div>
 <div class="card"><h2>死枝<small>被杀的因子与杀因</small></h2><div id="dead"></div></div>
</div>
<div class="card" id="chain" hidden></div>
<script>
const $=s=>document.querySelector(s);const f=(x,d=3)=>x==null?'—':Number(x).toFixed(d);
function spark(pts){if(!pts||pts.length<2)return'';const w=90,h=22,ys=pts.map(p=>p[1]),mn=Math.min(...ys,0),mx=Math.max(...ys,0),r=(mx-mn)||1;
 const X=i=>i/(pts.length-1)*w,Y=y=>h-((y-mn)/r)*h;const z=Y(0);
 return`<svg class="spark" viewBox="0 0 ${w} ${h}"><line x1="0" y1="${z}" x2="${w}" y2="${z}"/><path d="${pts.map((p,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(p[1]).toFixed(1)).join(' ')}"/></svg>`}
async function load(){const s=await (await fetch('/api/state')).json();
 $('#sub').textContent=`${s.db} · ${s.total} 个因子登记 · ${s.evals} 次评估 · 更新 ${s.now}`;
 $('#minn').textContent=s.min_n;
 const live=s.live.slice(0,s.max_live);$('#slots').innerHTML=Array.from({length:s.max_live},(_,i)=>`<div class="slot ${live[i]?'on':''}">${live[i]?`<span>${live[i].name}</span>`:''}</div>`).join('');
 $('#budget').innerHTML=`live <b>${s.live.length}</b> / ${s.max_live}`;$('#meta').textContent=`沙箱 通过 ${s.sandbox.ok} · 拒 ${s.sandbox.fail}`;
 $('#board').innerHTML=s.board.length?`<table><tr><th>因子</th><th>IC</th><th>t</th><th>命中</th><th>天</th><th>口径</th><th>判定</th><th>20日</th></tr>`+
  s.board.map(r=>`<tr class="row" data-id="${r.id}"><td>${r.name}<span class="tag ${r.status}">${r.status}</span></td><td class="num">${f(r.ic_mean,4)}</td><td class="num">${f(r.ic_t,2)}</td><td class="num">${f(r.hit,2)}</td><td class="num">${r.n_obs}</td><td>${r.settlement}</td><td class="v-${r.verdict}">${r.verdict}</td><td>${spark(r.roll20)}</td></tr>`).join('')+`</table>`
  :`<p class="empty">没有 n ≥ ${s.min_n} 天的评估。跑一次:<code>python3 ic_eval_v1_1.py run --db &lt;bars.db&gt; --factor mom_5 --horizon 5 --lineage-id &lt;id&gt;</code></p>`;
 $('#dead').innerHTML=s.dead.length?`<ul class="dead">`+s.dead.map(d=>`<li><b>${d.name}</b> <small>${d.reason}</small></li>`).join('')+`</ul>`:`<p class="empty">还没有被杀的因子。一个都没杀,通常说明闸没在工作。</p>`;
 document.querySelectorAll('tr.row').forEach(tr=>tr.onclick=()=>chain(tr.dataset.id));}
async function chain(id){const c=await (await fetch('/api/lineage?id='+id)).json();const el=$('#chain');el.hidden=false;
 const st=[];c.ancestors.slice().reverse().forEach(a=>st.push(`<div class="step anc"><div class="t">祖先 #${a.id}</div><div>${a.name} <small>${a.expr}</small></div></div>`));
 const fa=c.factor;st.push(`<div class="step"><div class="t">提出 ${fa.ts}</div><div><b>${fa.name}</b><span class="tag ${fa.status}">${fa.status}</span><br><small>${fa.expr}</small><br><small>${fa.origin} · ${fa.proposer||''} · ${fa.econ_rationale||'(无经济含义)'}${fa.reject_reason?' · 杀因:'+fa.reject_reason:''}</small></div></div>`);
 c.sandbox.forEach(x=>st.push(`<div class="step"><div class="t">沙箱 ${x.ts}</div><div>${x.ok?'通过':'拒'} <small>${x.receipt_path||''} ${x.error||''}</small></div></div>`));
 c.evals.forEach(e=>st.push(`<div class="step"><div class="t">评估 ${e.ts}</div><div><span class="v-${e.verdict}">${e.verdict}</span> IC ${f(e.ic_mean,4)} t ${f(e.ic_t,2)} n ${e.n_obs} ${e.horizon} ${e.settlement} <small>${e.reason||''} ${e.receipt_path||''}</small></div></div>`));
 el.innerHTML=`<a class="close" href="#" onclick="this.parentNode.hidden=true;return false">收起</a><h2>#${fa.id} 的链</h2>`+st.join('');el.scrollIntoView({behavior:'smooth'});}
load();</script></body></html>"""


def _dt(ts):
    import datetime as _d
    return _d.datetime.fromtimestamp(float(ts)).strftime("%m-%d %H:%M") if ts else ""


def state(db_path: str) -> dict:
    import factor_lineage_v1_1 as FL
    con = FL.connect(db_path)
    try:
        board = FL.leaderboard(limit=50, con=con)
        for r in board:
            r["roll20"] = _roll20(con, r["id"])
        live = [dict(x) for x in con.execute("SELECT id,name FROM factors WHERE status='live' ORDER BY last_touch")]
        dead = [{"id": d["id"], "name": d["name"], "reason": d["reject_reason"]} for d in FL.dead_branches(con=con)]
        sb = con.execute("SELECT SUM(ok), COUNT(*)-SUM(ok) FROM sandbox").fetchone()
        import time as _t
        return {"db": os.path.basename(db_path), "now": _t.strftime("%H:%M:%S"), "min_n": FL.MIN_N, "max_live": FL.MAX_LIVE,
                "total": FL.budget(con=con)["total"], "evals": con.execute("SELECT COUNT(*) FROM evals").fetchone()[0],
                "live": live, "board": board, "dead": dead, "sandbox": {"ok": sb[0] or 0, "fail": sb[1] or 0}}
    finally:
        con.close()


def _roll20(con, fid: int):
    """最近一次足样本评估没有存逐日 IC;这里用该因子历次评估的 ic_mean 序列代替(每次评估一个点)。"""
    rows = con.execute("SELECT ts, ic_mean FROM evals WHERE factor_id=? AND ic_mean IS NOT NULL ORDER BY ts", (fid,)).fetchall()
    return [[r[0], r[1]] for r in rows][-20:]


def lineage(db_path: str, fid: int) -> dict:
    import factor_lineage_v1_1 as FL
    con = FL.connect(db_path)
    try:
        ln = FL.lineage(fid, con=con)
        for k in ("factor",):
            ln[k]["ts"] = _dt(ln[k]["ts"])
        for a in ln["ancestors"]:
            a["ts"] = _dt(a["ts"])
        for x in ln["sandbox"] + ln["evals"]:
            x["ts"] = _dt(x["ts"])
        return ln
    finally:
        con.close()


def make_handler(db_path: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 静默
            pass

        def _send(self, code, body, ctype):
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            try:
                if u.path == "/":
                    return self._send(200, HTML.encode(), "text/html; charset=utf-8")
                if u.path == "/api/state":
                    return self._send(200, json.dumps(state(db_path), ensure_ascii=False, default=str).encode(), "application/json")
                if u.path == "/api/lineage":
                    fid = int(parse_qs(u.query).get("id", ["0"])[0])
                    return self._send(200, json.dumps(lineage(db_path, fid), ensure_ascii=False, default=str).encode(), "application/json")
                return self._send(404, b"not found", "text/plain")
            except Exception as e:  # noqa
                return self._send(500, json.dumps({"error": str(e)}).encode(), "application/json")
    return H


def demo_db(path: str) -> None:
    """合成:6 个因子跑真 IC 评估(随机游走数据),看仪表长什么样。数字没有意义。"""
    import tempfile, factor_lineage_v1_1 as FL, ic_eval_v1_1 as IE
    os.environ["FACTOR_LINEAGE_DB"] = path
    bars_db = os.path.join(tempfile.mkdtemp(), "bars.db"); IE._synthetic_db(bars_db, n_sym=80, n_days=260)
    bars = IE.load_bars(bars_db)
    for name, expr, why in [("mom_5", "close/close[-5]-1", "短期动量延续"), ("mom_20", "close/close[-20]-1", "月度动量"),
                            ("rev_1", "-(close/close[-1]-1)", "隔日反转"), ("vol_20", "-std(ret,20)", "低波动溢价")]:
        fid = FL.propose(expr, name, "manual", None, "demo", why)
        FL.record_sandbox(fid, True, "factor_reviews:demo")
        s = IE.evaluate(bars, IE.FACTORS[name], 5)
        IE.write_lineage(s, fid, "demo", *IE.auto_verdict(s))
    d = FL.propose("close/close[-5]-1 * 1.0", "mom_5_dup", "llm", None, "glm52", "同 mom_5")     # 去重:回到同 id
    FL.record_dead_proposal("weird(open,high)", "no_reason", "llm", "glm52")
    k = FL.propose("oracle_demo", "oracle_demo", "manual", [1], "demo", "处决案专用,未来收益本身")
    FL.record_sandbox(k, True, "demo"); s = IE.evaluate(bars, IE.FACTORS["oracle_5"], 5); IE.write_lineage(s, k, "demo", *IE.auto_verdict(s)); FL.promote(k)
    FL.reject(2, "与 mom_5 相关 0.91,重复暴露")


def _main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("FACTOR_LINEAGE_DB", os.path.join("state", "factor_lineage.db")))
    ap.add_argument("--port", type=int, required=True, help="先登记 PORTS.md 再 bind")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--once", action="store_true", help="只打印 /api/state 的 JSON,不起服务(自检用)")
    a = ap.parse_args(argv[1:])
    if a.demo:
        import tempfile
        a.db = os.path.join(tempfile.mkdtemp(), "demo_lineage.db"); demo_db(a.db)
    if a.once:
        print(json.dumps(state(a.db), ensure_ascii=False, default=str)); return 0
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.db))
    print(f"lineage dashboard · http://127.0.0.1:{a.port}/ · db={a.db} · 只读")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
