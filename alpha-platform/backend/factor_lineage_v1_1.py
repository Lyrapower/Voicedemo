"""factor_lineage v1.1 · 因子 lineage 账(2026-09-02,砥;v1.1 加 record_dead_proposal:无经济含义的提案记账即死)

一张表两件事:每个 propose 过的因子留一行;每次评估留一行。零新依赖(sqlite3 标准库)。
不做搜索、不做 mutation/crossover/bandit——那些等这张表有真数再拍。

规矩(8-26 Lyra):
- 因子必须带经济含义(econ_rationale 非空),否则拒收。
- live 因子预算 ≤ MAX_LIVE(默认 12),第 13 个 promote 即拒。
- IC 口径:调用方传入(settlement 字段记结算口径,如 theta_mid);n_obs < MIN_N 的评估只记不裁。
- 同一表达式(去空白、小写)只有一个 id;再次 propose 记一次 reuse 触碰,不新建。

接入点(戌 grep 后挂,三处,函数名以 factory_pipeline 实况为准):
  1) propose 处:   fid = propose(expr, name, origin, parent_ids, proposer, econ_rationale, universe)
  2) 沙箱结果处:   record_sandbox(fid, ok, receipt_path, error)
  3) IC 出数处:    record_eval(fid, window_start, window_end, horizon, n_obs, ic_mean, ic_std, settlement, second_source_ok, receipt_path, verdict, reason)
  否决处:          reject(fid, reason);  晋级处: promote(fid)
  hypothesis 为空:  record_dead_proposal(expr, name, origin, proposer)  # 记账并判死,不回退默认理由

CLI:
  python3 factor_lineage_v1.py selftest        # 处决案七条,任一红即非零退出
  python3 factor_lineage_v1.py leaderboard     # 按 ic_t 排,只含 n_obs>=MIN_N
  python3 factor_lineage_v1.py dead            # 死枝:rejected + 原因
  python3 factor_lineage_v1.py show <id>       # 单因子全链(祖先 + 评估)
  python3 factor_lineage_v1.py budget          # live 计数 / 上限
库路径:环境变量 FACTOR_LINEAGE_DB,默认 ./state/factor_lineage.db
"""
from __future__ import annotations
import hashlib, json, os, sqlite3, sys, time
from typing import Any, Iterable

MAX_LIVE = int(os.environ.get("FACTOR_MAX_LIVE", "12"))
MIN_N = int(os.environ.get("FACTOR_MIN_N", "60"))
ORIGINS = {"llm", "manual", "reuse", "mutation", "crossover"}
STATUSES = {"proposed", "sandbox_ok", "sandbox_fail", "rejected", "live", "retired"}
VERDICTS = {"keep", "reject", "watch", "insufficient"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS factors(
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  expr TEXT NOT NULL,
  expr_hash TEXT NOT NULL UNIQUE,
  name TEXT,
  origin TEXT NOT NULL,
  parent_ids TEXT NOT NULL DEFAULT '[]',
  proposer TEXT,
  econ_rationale TEXT NOT NULL,
  universe TEXT,
  status TEXT NOT NULL DEFAULT 'proposed',
  reuse_count INTEGER NOT NULL DEFAULT 0,
  last_touch REAL,
  reject_reason TEXT,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS evals(
  id INTEGER PRIMARY KEY,
  factor_id INTEGER NOT NULL REFERENCES factors(id),
  ts REAL NOT NULL,
  window_start TEXT, window_end TEXT, horizon TEXT,
  n_obs INTEGER NOT NULL,
  ic_mean REAL, ic_std REAL, ic_t REAL,
  settlement TEXT NOT NULL,
  second_source_ok INTEGER,
  receipt_path TEXT,
  verdict TEXT NOT NULL,
  reason TEXT
);
CREATE TABLE IF NOT EXISTS sandbox(
  id INTEGER PRIMARY KEY,
  factor_id INTEGER NOT NULL REFERENCES factors(id),
  ts REAL NOT NULL,
  ok INTEGER NOT NULL,
  receipt_path TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS ix_evals_factor ON evals(factor_id);
CREATE INDEX IF NOT EXISTS ix_factors_status ON factors(status);
"""


def _db_path() -> str:
    p = os.environ.get("FACTOR_LINEAGE_DB") or os.path.join("state", "factor_lineage.db")
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    return p


def connect(path: str | None = None) -> sqlite3.Connection:
    p = path or _db_path()
    readonly = os.environ.get("FACTOR_LINEAGE_DB_READONLY") == "1"
    if readonly:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    if not readonly:
        con.executescript(SCHEMA)
    return con


def normalize_expr(expr: str) -> str:
    return "".join(str(expr).split()).lower()


def expr_hash(expr: str) -> str:
    return hashlib.sha256(normalize_expr(expr).encode()).hexdigest()[:16]


class LineageError(ValueError):
    pass


# ---------- 写入口 ----------

def propose(expr: str, name: str, origin: str, parent_ids: Iterable[int] | None,
            proposer: str, econ_rationale: str, universe: str = "", notes: str = "",
            con: sqlite3.Connection | None = None) -> int:
    """登记一个因子。同表达式已存在 → 返回旧 id 并 reuse_count+1,不新建。"""
    if origin not in ORIGINS:
        raise LineageError(f"origin 不在 {sorted(ORIGINS)}: {origin!r}")
    if not (econ_rationale or "").strip():
        raise LineageError("econ_rationale 为空:因子必须有经济含义(8-26 规矩),拒收")
    if not (expr or "").strip():
        raise LineageError("expr 为空")
    parents = sorted({int(p) for p in (parent_ids or [])})
    own = con is None
    con = con or connect()
    try:
        h = expr_hash(expr)
        row = con.execute("SELECT id FROM factors WHERE expr_hash=?", (h,)).fetchone()
        now = time.time()
        if row:
            con.execute("UPDATE factors SET reuse_count=reuse_count+1, last_touch=? WHERE id=?", (now, row["id"]))
            con.commit()
            return int(row["id"])
        for p in parents:
            if not con.execute("SELECT 1 FROM factors WHERE id=?", (p,)).fetchone():
                raise LineageError(f"parent_id {p} 不存在")
        cur = con.execute(
            "INSERT INTO factors(ts,expr,expr_hash,name,origin,parent_ids,proposer,econ_rationale,universe,last_touch,notes)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (now, expr, h, name, origin, json.dumps(parents), proposer, econ_rationale.strip(), universe, now, notes))
        con.commit()
        return int(cur.lastrowid)
    finally:
        if own:
            con.close()


def record_dead_proposal(expr: str, name: str, origin: str, proposer: str, reason: str = "无经济含义(hypothesis 为空)",
                         universe: str = "", con: sqlite3.Connection | None = None) -> int:
    """无经济含义的提案:记账并直接判死。不占预算、不上榜、进死枝。同表达式已存在 → 只 reuse+1,不改其状态。"""
    if origin not in ORIGINS:
        raise LineageError(f"origin 不在 {sorted(ORIGINS)}: {origin!r}")
    own = con is None
    con = con or connect()
    try:
        h = expr_hash(expr); now = time.time()
        row = con.execute("SELECT id FROM factors WHERE expr_hash=?", (h,)).fetchone()
        if row:
            con.execute("UPDATE factors SET reuse_count=reuse_count+1, last_touch=? WHERE id=?", (now, row["id"]))
            con.commit(); return int(row["id"])
        cur = con.execute(
            "INSERT INTO factors(ts,expr,expr_hash,name,origin,parent_ids,proposer,econ_rationale,universe,status,reject_reason,last_touch)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, expr, h, name, origin, "[]", proposer, "", universe, "rejected", reason, now))
        con.commit(); return int(cur.lastrowid)
    finally:
        if own: con.close()


def record_sandbox(factor_id: int, ok: bool, receipt_path: str = "", error: str = "",
                   con: sqlite3.Connection | None = None) -> None:
    own = con is None
    con = con or connect()
    try:
        _require(con, factor_id)
        con.execute("INSERT INTO sandbox(factor_id,ts,ok,receipt_path,error) VALUES(?,?,?,?,?)",
                    (factor_id, time.time(), 1 if ok else 0, receipt_path, error))
        con.execute("UPDATE factors SET status=?, last_touch=? WHERE id=? AND status IN ('proposed','sandbox_ok','sandbox_fail')",
                    ("sandbox_ok" if ok else "sandbox_fail", time.time(), factor_id))
        con.commit()
    finally:
        if own:
            con.close()


def record_eval(factor_id: int, window_start: str, window_end: str, horizon: str, n_obs: int,
                ic_mean: float | None, ic_std: float | None, settlement: str,
                second_source_ok: bool | None, receipt_path: str, verdict: str, reason: str = "",
                con: sqlite3.Connection | None = None) -> int:
    """记一次 IC 评估。n_obs < MIN_N 时 verdict 强制为 insufficient(只记不裁)。"""
    if not (settlement or "").strip():
        raise LineageError("settlement 为空:必须写结算口径(如 theta_mid)")
    if verdict not in VERDICTS:
        raise LineageError(f"verdict 不在 {sorted(VERDICTS)}: {verdict!r}")
    own = con is None
    con = con or connect()
    try:
        _require(con, factor_id)
        ic_t = None
        if ic_mean is not None and ic_std not in (None, 0) and n_obs > 1:
            ic_t = float(ic_mean) / (float(ic_std) / (n_obs ** 0.5))
        if n_obs < MIN_N:
            verdict, reason = "insufficient", (reason + f" | n_obs={n_obs}<MIN_N={MIN_N}").strip(" |")
        cur = con.execute(
            "INSERT INTO evals(factor_id,ts,window_start,window_end,horizon,n_obs,ic_mean,ic_std,ic_t,settlement,"
            "second_source_ok,receipt_path,verdict,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (factor_id, time.time(), window_start, window_end, horizon, int(n_obs), ic_mean, ic_std, ic_t,
             settlement, None if second_source_ok is None else int(bool(second_source_ok)), receipt_path, verdict, reason))
        con.execute("UPDATE factors SET last_touch=? WHERE id=?", (time.time(), factor_id))
        con.commit()
        return int(cur.lastrowid)
    finally:
        if own:
            con.close()


def reject(factor_id: int, reason: str, con: sqlite3.Connection | None = None) -> None:
    if not (reason or "").strip():
        raise LineageError("reject 必须带原因")
    own = con is None
    con = con or connect()
    try:
        _require(con, factor_id)
        con.execute("UPDATE factors SET status='rejected', reject_reason=?, last_touch=? WHERE id=?",
                    (reason.strip(), time.time(), factor_id))
        con.commit()
    finally:
        if own:
            con.close()


def promote(factor_id: int, con: sqlite3.Connection | None = None) -> None:
    """晋级为 live。预算 MAX_LIVE 硬闸;须有至少一次 verdict=keep 且 n_obs>=MIN_N 的评估。"""
    own = con is None
    con = con or connect()
    try:
        _require(con, factor_id)
        live = con.execute("SELECT COUNT(*) FROM factors WHERE status='live'").fetchone()[0]
        cur = con.execute("SELECT status FROM factors WHERE id=?", (factor_id,)).fetchone()["status"]
        if cur == "live":
            return
        if live >= MAX_LIVE:
            raise LineageError(f"live 因子已 {live} ≥ MAX_LIVE={MAX_LIVE},预算满,拒绝晋级 {factor_id}")
        ok = con.execute("SELECT 1 FROM evals WHERE factor_id=? AND verdict='keep' AND n_obs>=? LIMIT 1",
                         (factor_id, MIN_N)).fetchone()
        if not ok:
            raise LineageError(f"因子 {factor_id} 无 verdict=keep 且 n_obs≥{MIN_N} 的评估,不能晋级")
        con.execute("UPDATE factors SET status='live', last_touch=? WHERE id=?", (time.time(), factor_id))
        con.commit()
    finally:
        if own:
            con.close()


def retire(factor_id: int, reason: str, con: sqlite3.Connection | None = None) -> None:
    own = con is None
    con = con or connect()
    try:
        _require(con, factor_id)
        con.execute("UPDATE factors SET status='retired', notes=COALESCE(notes,'')||?, last_touch=? WHERE id=?",
                    (f" [retired: {reason}]", time.time(), factor_id))
        con.commit()
    finally:
        if own:
            con.close()


# ---------- 读出口 ----------

def lineage(factor_id: int, con: sqlite3.Connection | None = None) -> dict[str, Any]:
    """单因子全链:自身 + 祖先(按 parent_ids 递归)+ 沙箱 + 评估。"""
    own = con is None
    con = con or connect()
    try:
        _require(con, factor_id)
        seen, chain, stack = set(), [], [factor_id]
        while stack:
            fid = stack.pop()
            if fid in seen:
                continue
            seen.add(fid)
            r = dict(con.execute("SELECT * FROM factors WHERE id=?", (fid,)).fetchone())
            chain.append(r)
            stack.extend(json.loads(r["parent_ids"]))
        evals = [dict(x) for x in con.execute("SELECT * FROM evals WHERE factor_id=? ORDER BY ts", (factor_id,))]
        sb = [dict(x) for x in con.execute("SELECT * FROM sandbox WHERE factor_id=? ORDER BY ts", (factor_id,))]
        return {"factor": chain[0], "ancestors": chain[1:], "sandbox": sb, "evals": evals}
    finally:
        if own:
            con.close()


def leaderboard(limit: int = 20, con: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """最新一次 n_obs≥MIN_N 的评估,按 ic_t 降序;rejected/retired 不上榜。"""
    own = con is None
    con = con or connect()
    try:
        rows = con.execute(
            "SELECT f.id, f.name, f.status, f.origin, e.ic_mean, e.ic_std, e.ic_t, e.n_obs, e.settlement, e.verdict, e.ts"
            " FROM factors f JOIN evals e ON e.factor_id=f.id"
            " WHERE e.n_obs>=? AND f.status NOT IN ('rejected','retired')"
            "   AND e.id=(SELECT id FROM evals WHERE factor_id=f.id AND n_obs>=? ORDER BY ts DESC LIMIT 1)"
            " ORDER BY COALESCE(e.ic_t,-1e9) DESC LIMIT ?", (MIN_N, MIN_N, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            con.close()


def dead_branches(con: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own = con is None
    con = con or connect()
    try:
        return [dict(r) for r in con.execute(
            "SELECT id,name,expr,origin,reject_reason,last_touch FROM factors WHERE status='rejected' ORDER BY last_touch DESC")]
    finally:
        if own:
            con.close()


def budget(con: sqlite3.Connection | None = None) -> dict[str, int]:
    own = con is None
    con = con or connect()
    try:
        live = con.execute("SELECT COUNT(*) FROM factors WHERE status='live'").fetchone()[0]
        total = con.execute("SELECT COUNT(*) FROM factors").fetchone()[0]
        return {"live": live, "max_live": MAX_LIVE, "total": total}
    finally:
        if own:
            con.close()


def _require(con: sqlite3.Connection, factor_id: int) -> None:
    if not con.execute("SELECT 1 FROM factors WHERE id=?", (factor_id,)).fetchone():
        raise LineageError(f"factor_id {factor_id} 不存在")


# ---------- 处决案 ----------

def selftest() -> int:
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "fl.db")
    con = connect(path)
    fails: list[str] = []

    def must(cond: bool, msg: str) -> None:
        (fails.append(msg) if not cond else None)

    # 1 无经济含义 → 拒收
    try:
        propose("ret_5d / vol_20d", "f_bad", "llm", None, "glm52", "   ", con=con); must(False, "1 空 rationale 未拒")
    except LineageError:
        pass
    # 2 同表达式去空白/大小写 → 同 id,reuse+1
    a = propose("RET_5d / VOL_20d", "f1", "llm", None, "glm52", "短期收益对波动的归一,动量风险调整", con=con)
    b = propose("ret_5d/vol_20d", "f1_dup", "llm", None, "glm53", "同上", con=con)
    must(a == b, f"2 去重失败 {a}!={b}")
    must(con.execute("SELECT reuse_count FROM factors WHERE id=?", (a,)).fetchone()[0] == 1, "2 reuse_count 未加")
    # 3 origin 白名单
    try:
        propose("x", "f", "magic", None, "p", "r", con=con); must(False, "3 非法 origin 未拒")
    except LineageError:
        pass
    # 4 n_obs<MIN_N → insufficient 只记不裁;promote 拒
    record_eval(a, "2026-08-01", "2026-08-15", "1d", 10, 0.05, 0.10, "theta_mid", True, "r1.md", "keep", con=con)
    must(con.execute("SELECT verdict FROM evals WHERE factor_id=?", (a,)).fetchone()[0] == "insufficient", "4 小样本未标 insufficient")
    try:
        promote(a, con=con); must(False, "4 小样本晋级未拒")
    except LineageError:
        pass
    # 5 足样本 keep → 可晋级;ic_t 计算
    e = record_eval(a, "2026-06-01", "2026-08-31", "1d", 80, 0.04, 0.08, "theta_mid", True, "r2.md", "keep", con=con)
    t = con.execute("SELECT ic_t FROM evals WHERE id=?", (e,)).fetchone()[0]
    must(abs(t - 0.04 / (0.08 / 80 ** 0.5)) < 1e-9, f"5 ic_t 错 {t}")
    promote(a, con=con)
    must(con.execute("SELECT status FROM factors WHERE id=?", (a,)).fetchone()[0] == "live", "5 未晋级")
    # 6 预算闸:再造 MAX_LIVE 个并晋级,第 MAX_LIVE+1 个拒
    ids = []
    for i in range(MAX_LIVE):
        fid = propose(f"f_{i} = close/open - {i}", f"f_{i}", "manual", [a], "lyra", "测试因子", con=con)
        record_eval(fid, "2026-06-01", "2026-08-31", "1d", 80, 0.02, 0.05, "theta_mid", True, "r.md", "keep", con=con)
        ids.append(fid)
    promoted = 0
    for fid in ids:
        try:
            promote(fid, con=con); promoted += 1
        except LineageError:
            break
    must(promoted == MAX_LIVE - 1, f"6 预算闸错:晋级 {promoted} 个,应 {MAX_LIVE - 1}(a 已占 1)")
    # 7 reject 带原因进死枝;lineage 祖先链
    reject(ids[0], "IC 与 f1 相关 0.97,重复暴露", con=con)
    dead = dead_branches(con=con)
    must(len(dead) == 1 and "0.97" in dead[0]["reject_reason"], "7 死枝未记原因")
    ln = lineage(ids[1], con=con)
    must([x["id"] for x in ln["ancestors"]] == [a], "7 祖先链错")
    # 8 无 settlement 口径 → 拒
    try:
        record_eval(a, "x", "y", "1d", 80, 0.1, 0.1, "", True, "", "keep", con=con); must(False, "8 空 settlement 未拒")
    except LineageError:
        pass
    # 9 榜只含足样本、非死枝
    lb = leaderboard(con=con)
    must(all(r["n_obs"] >= MIN_N for r in lb) and all(r["id"] != ids[0] for r in lb), "9 榜含小样本或死枝")
    # 10 无理由提案:记账即死,不占预算
    d = record_dead_proposal("weird_expr_no_reason", "f_noreason", "llm", "glm52", con=con)
    must(con.execute("SELECT status FROM factors WHERE id=?", (d,)).fetchone()[0] == "rejected", "10 无理由提案未判死")
    must(any(x["id"] == d for x in dead_branches(con=con)), "10 无理由提案不在死枝")
    try:
        promote(d, con=con); must(False, "10 死提案被晋级")
    except LineageError:
        pass
    con.close()
    if fails:
        print("SELFTEST FAIL"); [print(" -", f) for f in fails]; return 1
    print(f"SELFTEST PASS 10/10 (MAX_LIVE={MAX_LIVE}, MIN_N={MIN_N}) db={path}")
    return 0


def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "selftest"
    if cmd == "selftest":
        return selftest()
    if cmd == "leaderboard":
        for r in leaderboard():
            print(f"#{r['id']:<4} {r['name']:<24} {r['status']:<10} ic={r['ic_mean']:.4f} t={r['ic_t']:.2f} n={r['n_obs']} {r['settlement']} {r['verdict']}")
        return 0
    if cmd == "dead":
        for r in dead_branches():
            print(f"#{r['id']:<4} {r['name']:<24} {r['reject_reason']}")
        return 0
    if cmd == "budget":
        print(json.dumps(budget()))
        return 0
    if cmd == "show" and len(argv) > 2:
        print(json.dumps(lineage(int(argv[2])), ensure_ascii=False, indent=1, default=str))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
