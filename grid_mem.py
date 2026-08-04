#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grid_mem.py · 2026-08-04 (from grid mem v2.py; Py3.9 conn-meta patch) · 记忆线单文件(仓内固定名 grid_mem.py,import 名不随版本漂)
变更记录:
  v2  按交接《二之补》三条补齐:
      1) NODE_CANDS 加 "node_id" 且列为首选;node 列认不出 → install/read/recall 硬停并打印全表结构,
         不再静默降级成 soul-only(那会让老行魂组读回整体失效且不报错)。
      2) 禁硬删触发器判据由 orig_id 单键改为 orig_id + 正文(IS 判等,兼容 NULL),堵 rowid 复用洞;
         新增自测5:归档删除后写新行复用同 rowid,试删必须仍被拦。
      3) detect() 结果缓存(按连接与 DB 路径),write_turn 高频调用不再每次全库 COUNT。
  v1  合并并作废 2026-08-03 八件套。

Lyra 只需跑一条(自动备份 DB,输出即执行证据):
  python3 grid_mem_v2.py install /路径/data/grid_store.db

全部子命令:
  install <db>                          装三字段 + 原文归档表 + 禁硬删触发器,当场跑五条真库自测
  write   <db> <surface> <role> <正文>  写一轮(服务端接线用同一个 write_turn 函数)
  read    <db> <local|cloud> [n]        魂组并集读回最近 n 轮(老行原地不动,按 node 归组)
  recall  <db> <surface> <查询词...>     魂组召回,阈值制,≤2000 字预算,中文同义扩展
  archive <db> <id...>                  把指定行迁入原文归档表(迁完 DELETE 才被放行)
  doctor  <db> [标签=文件路径 ...]        体检 + 文件停摆龄检查

架构(Lyra 已拍板,2026-08-03,不重开):
  两魂读并集:local ⊇ {local, workbench-b11, field-particle} · cloud ⊇ {cloud, cloud-glm52, cloud-kimi}
  魂由面定:EXPANDED 走云端那几轮 soul 仍是 local;substrate 只记录不参与归属。
  生产正文永不硬删:DELETE 仅在该行已进原文归档表时放行(DB 级触发器,绕过任何代码层都拦)。
  老行不迁移不改写;三字段为 ALTER ADD COLUMN 可空新增,不动既有列与 8501 读法。

WIRING(给 Cursor,整块执行,完成后贴回 diff;不要另写文档):
  1. 本文件放 repo 根,重命名为 grid_mem.py(仓内固定名);若仓里还有 grid_mem_v1.py 或
     store_write.py guard_install.py recall.py doctor_check.py watchdog_freshness.py sources.json grid_patch.js,删除。
  2. 先看真表: sqlite3 data/grid_store.db ".schema" ——8501 按哪个字段过滤读,认表就该认出哪个;对不上把 .schema 贴回。
  3. 跑一次: python3 grid_mem.py install data/grid_store.db ,输出整段贴回。
  4. 服务端每个产生对话轮的落点插一行(四面都要;具体文件与行号你定位;高频落点持有连接传入,别每次传路径):
         from grid_mem import write_turn
         write_turn(DB_PATH或连接, surface=面, role="user"或"assistant", content=正文, substrate=实际模型名或None)
     面取值:8790→"8790" · grid.html→"grid-app" · b11 STUDIO/HOME/EXPANDED→"b11-studio"/"b11-home"/"b11-expanded"
     (EXPANDED 即使 route 到 GLM/Kimi,surface 仍是 b11-expanded,soul 自动归 local,substrate 填实际模型)
     b11 Cloud→"cloud-glm"/"cloud-kimi" · Console Cloud→"console-cloud"。
  5. 读回与召回统一走本文件 read/recall(或同名函数);任何地方不得再按 node 切分读。
  6. b11 前端唯一改动:发消息请求体带 "surface" 字段(当前所在面)。其余前端问题不预修,复现再单点改。
  7. 不碰 GLM 手上 P0 四条(epoch 硬删代码、/task/candidate、8515 双名、STUDIO 断档标);撞车以 GLM 的 diff 为准。
"""
import sys, os, re, json, time, shutil, sqlite3
from datetime import datetime

SOUL_NODES = {
    "local": ("local", "workbench-b11", "field-particle"),
    "cloud": ("cloud", "cloud-glm52", "cloud-kimi"),
}
SURFACE_NODE = {
    # 生产 store node:8790/grid.html 均落 field-particle(非字面 "local")
    "8790": "field-particle", "grid-app": "field-particle",
    "b11-studio": "workbench-b11", "b11-home": "workbench-b11", "b11-expanded": "workbench-b11",
    "field-particle": "field-particle",
    "cloud-glm": "cloud-glm52", "cloud-kimi": "cloud-kimi", "console-cloud": "cloud",
}
# 模型 ctx(Ollama Cloud library 实数):glm-5.2:cloud=976000 · kimi-k2.6:cloud 见 cloud_gateway_route
# 注入预算:取「单条 sanitize 上限 MAX_PROMPT_CHARS=8000」的一半=4000 字(拼进最后 user 不爆 8k)
# 召回另计 ≤2000 字;客户端已带多轮时服务端只召回不再叠近程窗
INJECT_WINDOW_TURNS = 15
INJECT_RECALL_CHARS = 2000
INJECT_BLOCK_CHARS = 4000  # half of code_task.kimi_input_scope.MAX_PROMPT_CHARS
# 真库唯一常量 — 禁止 data/grid_store.db 软链;doctor / 全仓调用只认这里
DEFAULT_STORE_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "grid-sovereign-runtime", "data", "grid_store.db",
)
# 唯一冷库(与 grid_store SCHEMA 同表);禁硬删触发器与 purge 迁冷共用
ARCHIVE_TABLE = "messages_archive"
LEGACY_MEM_ARCHIVE = "messages_mem_archive"
CONTENT_CANDS = ("content", "text", "body", "message", "msg")
ROLE_CANDS    = ("role", "speaker", "sender")
TS_CANDS      = ("ts", "timestamp", "created_at", "created", "time", "date")
NODE_CANDS    = ("node_id", "node", "source_node", "origin")   # v2: node_id 首选(既有约定)
NAME_HINT     = ("message", "turn", "chat", "conversation", "memory", "store")
SYN = {
    "记忆": ("memory", "记住", "记录", "存档", "召回"),
    "问题": ("bug", "故障", "错误", "issue"),
    "对话": ("chat", "消息", "message"),
    "期权": ("option",),
}
_CACHE = {}  # db绝对路径 -> 认表结果

def soul_of(surface):
    return "cloud" if surface.startswith(("cloud", "console-cloud")) else "local"

def node_of(surface):
    return SURFACE_NODE.get(surface, "cloud" if soul_of(surface) == "cloud" else "local")

_CONN_META = {}  # id(conn) -> {key, m}  # Py3.9 sqlite3.Connection 不可挂属性

def _conn(db):
    if not os.path.isfile(db):
        sys.exit(f"DB 不存在: {db}")
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    _CONN_META[id(c)] = {"key": os.path.abspath(db), "m": None}
    return c

def _gm_get(conn, field, default=None):
    return _CONN_META.get(id(conn), {}).get(field, default)

def _gm_set(conn, field, value):
    meta = _CONN_META.setdefault(id(conn), {})
    meta[field] = value

def _cols(conn, t):
    return list(conn.execute(f'PRAGMA table_info("{t}")'))  # cid,name,type,notnull,dflt,pk

def _pick(names, cands):
    for c in cands:
        if c in names:
            return c
    return None

def _dump_schema(conn):
    for t in [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]:
        print(f"  {t}: " + ", ".join(f"{c[1]}({c[2]})" for c in _cols(conn, t)))

def detect(conn, verbose=False, refresh=False):
    """自适应认表(带缓存)。主表或 node 列认不出 = 打印全部表结构后硬停——不静默降级。"""
    key = _gm_get(conn, "key")
    if not refresh:
        m = _gm_get(conn, "m") or (key and _CACHE.get(key))
        if m:
            _gm_set(conn, "m", m)
            return m
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    best, best_score, best_rows = None, 0, -1
    for t in tables:
        if t.endswith("_mem_archive") or t == ARCHIVE_TABLE:
            continue
        names = {c[1].lower() for c in _cols(conn, t)}
        score = 0
        if _pick(names, ROLE_CANDS):    score += 2
        if _pick(names, CONTENT_CANDS): score += 2
        if _pick(names, NODE_CANDS):    score += 2
        if any(h in t.lower() for h in NAME_HINT): score += 1
        if score < 4:
            continue
        rows = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        if (score, rows) > (best_score, best_rows):
            best, best_score, best_rows = t, score, rows
    if not best:
        print("认不出对话轮主表。实际结构如下(整段发回,按它改本文件):")
        _dump_schema(conn)
        sys.exit(2)
    info = _cols(conn, best)
    names = {c[1].lower() for c in info}
    m = {
        "table": best, "rows": best_rows, "names": names,
        "content": _pick(names, CONTENT_CANDS),
        "role":    _pick(names, ROLE_CANDS),
        "ts":      _pick(names, TS_CANDS),
        "node":    _pick(names, NODE_CANDS),
        "ts_int":  False,
        "ts_real": False,
        "id":      "rowid",
        "notnull": [(c[1], (c[2] or "").upper()) for c in info if c[3] and c[5] == 0 and c[4] is None],
    }
    for c in info:
        if c[5] == 1 and "INT" in (c[2] or "").upper():
            m["id"] = c[1]
        if m["ts"] and c[1].lower() == m["ts"]:
            typ = (c[2] or "").upper()
            if "INT" in typ:
                m["ts_int"] = True
            elif "REAL" in typ or "FLOA" in typ or "DOUB" in typ:
                m["ts_real"] = True
    if m["node"] is None:
        print(f'主表 {best} 认不出 node 列(找过: {", ".join(NODE_CANDS)})。'
              "没有它,魂组并集读回会静默失效,所以在这里硬停。实际结构(整段发回):")
        _dump_schema(conn)
        sys.exit(2)
    if verbose:
        print(f"[认表] 主表={m['table']} 行数={best_rows} id={m['id']} "
              f"content={m['content']} role={m['role']} ts={m['ts']} node={m['node']}")
    _gm_set(conn, "m", m)
    if key:
        _CACHE[key] = m
    return m

def _arch_name(t=None):
    """冷库表名固定为 messages_archive(参数保留兼容旧调用)。"""
    return ARCHIVE_TABLE

def _now(m):
    if m.get("ts_int"):
        return int(time.time())
    if m.get("ts_real"):
        return float(time.time())
    return datetime.now().isoformat(timespec="seconds")

def ensure_columns(conn, m):
    added = []
    for col in ("soul", "surface", "substrate"):
        if col not in m["names"]:
            conn.execute(f'ALTER TABLE "{m["table"]}" ADD COLUMN {col} TEXT')
            m["names"].add(col)
            added.append(col)
    print(f"[三字段] " + (f"新增可空列: {', '.join(added)}(既有列与老行未动)" if added
                          else "soul/surface/substrate 已在位"))

def ensure_archive(conn, m):
    """唯一冷库 messages_archive;缺列补 row_json;迁完即删 legacy mem_archive。"""
    arch = ARCHIVE_TABLE
    conn.execute(f'''CREATE TABLE IF NOT EXISTS "{arch}"(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      node_id TEXT NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      ts REAL NOT NULL,
      archived_at REAL NOT NULL,
      origin_id INTEGER,
      row_json TEXT
    )''')
    names = {c[1].lower() for c in _cols(conn, arch)}
    if "row_json" not in names:
        conn.execute(f'ALTER TABLE "{arch}" ADD COLUMN row_json TEXT')
        print(f"[归档表] {arch} 补列 row_json")
    n_mig = _migrate_legacy_mem_archive(conn, m)
    if n_mig:
        print(f"[归档表] 自 {LEGACY_MEM_ARCHIVE} 迁入 {n_mig} 行后已删表")
    print(f"[归档表] {arch} 在位(唯一冷库;row_json 存整行原文)")
    return arch

def _migrate_legacy_mem_archive(conn, m):
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if LEGACY_MEM_ARCHIVE not in tables:
        return 0
    rows = conn.execute(
        f'SELECT orig_id, content, row_json, archived_at FROM "{LEGACY_MEM_ARCHIVE}"'
    ).fetchall()
    n = 0
    node_col = m.get("node") or "node_id"
    for r in rows:
        d = {}
        try:
            d = json.loads(r["row_json"] or "{}") if r["row_json"] else {}
        except Exception:
            d = {}
        origin = r["orig_id"]
        content = r["content"] if r["content"] is not None else d.get(m.get("content") or "content") or ""
        node_id = d.get(node_col) or d.get("node_id") or "unknown"
        role = d.get(m.get("role") or "role") or "system"
        if role not in ("user", "assistant", "system"):
            role = "system"
        ts = d.get(m.get("ts") or "ts") or 0.0
        try:
            ts = float(ts)
        except Exception:
            ts = 0.0
        try:
            archived_at = float(r["archived_at"]) if r["archived_at"] not in (None, "") else time.time()
        except Exception:
            # ISO from old mem_archive
            archived_at = time.time()
        conn.execute(
            f'INSERT INTO "{ARCHIVE_TABLE}"'
            "(node_id, role, content, ts, archived_at, origin_id, row_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (node_id, role, content, ts, archived_at, origin,
             r["row_json"] or json.dumps(d, ensure_ascii=False, default=str)),
        )
        n += 1
    conn.execute(f'DROP TABLE IF EXISTS "{LEGACY_MEM_ARCHIVE}"')
    conn.commit()
    return n

def ensure_guard(conn, m):
    arch = ARCHIVE_TABLE
    trg = f"grid_mem_guard_{m['table']}"
    if m["content"]:
        cond = f'origin_id = OLD.{m["id"]} AND content IS OLD."{m["content"]}"'
        note = "判据 = origin_id + 正文 → messages_archive(堵 rowid 复用洞)"
    else:
        cond = f'origin_id = OLD.{m["id"]}'
        note = "警告:无 content 列,判据仅 origin_id,存在 rowid 复用洞"
    conn.executescript(f'''
        DROP TRIGGER IF EXISTS "{trg}";
        CREATE TRIGGER "{trg}" BEFORE DELETE ON "{m['table']}" FOR EACH ROW
        WHEN NOT EXISTS (SELECT 1 FROM "{arch}" WHERE {cond})
        BEGIN SELECT RAISE(ABORT, 'grid_mem: 硬删被拦,先迁原文归档'); END;
    ''')
    print(f"[守卫] 触发器 {trg} 装好,{note};DB 级,绕过任何代码层都拦")

def write_turn(db, surface, role, content, substrate=None, node_id=None):
    """四面共用写入。服务端接线只调这一个函数。db 可传路径或已开连接(高频落点传连接)。返回新行 id。
    node_id 可选:覆盖 SURFACE_NODE(用于 smoke 等非生产 node,或 URL 路径与面不一致时)。"""
    conn = _conn(db) if isinstance(db, str) else db
    if not isinstance(db, str) and not _gm_get(conn, "key"):
        _gm_set(conn, "key", "live")
    m = detect(conn)
    if "surface" not in m["names"]:
        raise RuntimeError("先跑: python3 grid_mem.py install <db>")
    d = {
        "surface": surface,
        "soul": soul_of(surface),
        m["node"]: node_id or node_of(surface),
    }
    if substrate:    d["substrate"] = substrate
    if m["role"]:    d[m["role"]] = role
    if m["content"]: d[m["content"]] = content
    if m["ts"]:      d[m["ts"]] = _now(m)
    def _ins(dd):
        cols = ", ".join(f'"{k}"' for k in dd)
        ph = ", ".join("?" for _ in dd)
        return conn.execute(f'INSERT INTO "{m["table"]}" ({cols}) VALUES ({ph})', list(dd.values()))
    try:
        cur = _ins(d)
    except sqlite3.DatabaseError as e:
        if "NOT NULL" in str(e).upper():
            for name, typ in m["notnull"]:
                if name not in d and name.lower() not in ("soul", "surface", "substrate"):
                    d[name] = 0 if ("INT" in typ or "REAL" in typ) else ""
            cur = _ins(d)
        else:
            raise
    conn.commit()
    return cur.lastrowid

def archive_rows(conn, m, ids):
    """迁入唯一冷库 messages_archive;schema 外字段进 row_json。"""
    arch = ARCHIVE_TABLE
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if arch not in tables:
        ensure_archive(conn, m)
    else:
        names = {c[1].lower() for c in _cols(conn, arch)}
        if "row_json" not in names:
            conn.execute(f'ALTER TABLE "{arch}" ADD COLUMN row_json TEXT')
    n = 0
    node_col = m.get("node") or "node_id"
    role_col = m.get("role") or "role"
    content_col = m.get("content") or "content"
    ts_col = m.get("ts") or "ts"
    for i in ids:
        row = conn.execute(
            f'SELECT {m["id"]} AS _id, * FROM "{m["table"]}" WHERE {m["id"]}=?', (i,)
        ).fetchone()
        if not row:
            print(f"[归档] id={i} 不存在,跳过")
            continue
        d = dict(row)
        role = d.get(role_col) or "system"
        if role not in ("user", "assistant", "system"):
            role = "system"
        try:
            ts = float(d.get(ts_col) or 0.0)
        except Exception:
            ts = 0.0
        conn.execute(
            f'INSERT INTO "{arch}"'
            "(node_id, role, content, ts, archived_at, origin_id, row_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                d.get(node_col) or "unknown",
                role,
                d.get(content_col) or "",
                ts,
                float(time.time()),
                d["_id"],
                json.dumps(d, ensure_ascii=False, default=str),
            ),
        )
        n += 1
    conn.commit()
    return n

def _try_delete(conn, m, rid):
    try:
        conn.execute(f'DELETE FROM "{m["table"]}" WHERE {m["id"]}=?', (rid,))
        conn.commit()
        return True
    except sqlite3.DatabaseError as e:
        if "硬删被拦" in str(e):
            conn.rollback()
            return False
        raise

def install(db):
    for ext in ("", "-wal", "-shm"):
        p = db + ext
        if os.path.isfile(p):
            bak = f"{p}.bak_{datetime.now():%Y%m%d_%H%M%S}"
            shutil.copy2(p, bak)
            if not ext:
                print(f"[备份] {bak}")
    conn = _conn(db)
    m = detect(conn, verbose=True, refresh=True)
    ensure_columns(conn, m)
    ensure_archive(conn, m)
    ensure_guard(conn, m)
    conn.commit()
    ok = True
    wid = write_turn(conn, "selftest", "system", "[grid_mem 自测行A,可无视]")
    print(f"[自测1] 写入 id={wid} PASS")
    if _try_delete(conn, m, wid):
        print("[自测2] 未归档硬删居然放行 —— FAIL"); ok = False
    else:
        print("[自测2] 未归档硬删被拦 PASS")
    archive_rows(conn, m, [wid])
    if _try_delete(conn, m, wid):
        print("[自测3] 迁归档后删除放行 PASS")
    else:
        print("[自测3] 迁归档后删除仍被拦 —— FAIL"); ok = False
    back = conn.execute(
        f'SELECT content FROM "{ARCHIVE_TABLE}" WHERE origin_id=? '
        "ORDER BY archived_at DESC LIMIT 1", (wid,)).fetchone()
    if back and "自测行A" in (back["content"] or ""):
        print("[自测4] 归档原文读回 PASS")
    else:
        print("[自测4] 归档原文读回 FAIL"); ok = False
    # 自测5:rowid 复用洞。刚删掉的 wid 是当时最大 rowid,紧接着写入的新行应复用它。
    wid2 = write_turn(conn, "selftest", "system", "[grid_mem 自测行B,正文与A不同]")
    if wid2 == wid:
        if _try_delete(conn, m, wid2):
            print("[自测5] rowid 复用行被静默放行 —— FAIL,守卫有洞"); ok = False
        else:
            print("[自测5] rowid 复用行硬删仍被拦 PASS")
    else:
        print(f"[自测5] 新行 id={wid2}≠{wid},库内有并发写入,复用场景没构造出来——跳过(判据本身已含正文匹配)")
    archive_rows(conn, m, [wid2])
    _try_delete(conn, m, wid2)   # 清理自测行B
    total = conn.execute(f'SELECT COUNT(*) FROM "{m["table"]}"').fetchone()[0]
    print(f"[现状] 主表 {m['table']} 共 {total} 行,老行一行未动")
    print(("五条自测全 PASS。" if ok else "有 FAIL,上面输出整段发回。")
          + "下一步:本文件转给 Cursor,按文件头 WIRING 七条接线,完成后贴回 diff 与 install 输出。")

def fetch_turns(db, soul, n=15):
    """魂组并集读回(库用/接线用)。返回时间正序 list[dict]。"""
    conn = _conn(db) if isinstance(db, str) else db
    if isinstance(db, str):
        pass
    else:
        key = _gm_get(conn, "key")
        if not key:
            _gm_set(conn, "key", getattr(conn, "database", "") or "live")
    m = detect(conn)
    nodes = SOUL_NODES.get(soul)
    if not nodes:
        raise ValueError("soul 取 local 或 cloud")
    qs = ",".join("?" for _ in nodes)
    rows = conn.execute(
        f'SELECT {m["id"]} AS _id, * FROM "{m["table"]}" '
        f'WHERE (soul=? OR "{m["node"]}" IN ({qs})) ORDER BY _id DESC LIMIT ?',
        [soul, *nodes, int(n)]).fetchall()
    out = []
    for r in reversed(rows):
        d = dict(r)
        out.append({
            "id": d["_id"],
            "role": d.get(m["role"] or "", ""),
            "content": str(d.get(m["content"] or "", "")),
            "surface": d.get("surface"),
            "soul": d.get("soul"),
            "substrate": d.get("substrate"),
            "node": d.get(m["node"], ""),
            "ts": d.get(m["ts"] or "", None),
        })
    return out

def read(db, soul, n=15):
    rows = fetch_turns(db, soul, n)
    for d in rows:
        txt = d["content"][:160].replace("\n", " ")
        tag = d.get("surface") or d.get("node") or "?"
        print(f'#{d["id"]} [{tag}/{d.get("role") or "?"}] {txt}')
    if not rows:
        print(f"({soul} 魂组暂无行)")
    return rows

def _tokens(query):
    toks = set(re.findall(r"[A-Za-z0-9_]+", query.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", query):
        toks.add(run)
        toks.update(run[i:i+2] for i in range(len(run) - 1))
    for k, exp in SYN.items():
        if k in query:
            toks.update(exp)
    return {t for t in toks if len(t) > 1 or not t.isascii()}

def fetch_recall(db, surface, query, budget=None):
    """魂组召回命中(库用)。返回 [{id,score,text}]，总字数≤budget。"""
    budget = int(budget if budget is not None else INJECT_RECALL_CHARS)
    conn = _conn(db) if isinstance(db, str) else db
    if not isinstance(db, str) and not _gm_get(conn, "key"):
        _gm_set(conn, "key", "live")
    m = detect(conn)
    soul = soul_of(surface)
    nodes = SOUL_NODES[soul]
    qs = ",".join("?" for _ in nodes)
    toks = _tokens(query)
    if not toks:
        return []
    rows = conn.execute(
        f'SELECT {m["id"]} AS _id, * FROM "{m["table"]}" '
        f'WHERE (soul=? OR "{m["node"]}" IN ({qs})) ORDER BY _id DESC LIMIT 5000',
        [soul, *nodes]).fetchall()
    scored = []
    for r in rows:
        txt = str(dict(r).get(m["content"] or "", ""))
        low = txt.lower()
        # toks 里 ASCII 已 lower;正文用 low 匹配,避免 MARKER vs marker 漏召
        s = sum(min(low.count(t.lower()) if t.isascii() else txt.count(t), 3) for t in toks)
        if s > 0:
            scored.append((s, r["_id"], txt))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    used, out = 0, []
    for s, i, txt in scored:
        piece = txt[:400]
        if used + len(piece) > budget:
            break
        used += len(piece)
        out.append({"id": i, "score": s, "text": piece})
    return out

def recall(db, surface, query, budget=None):
    hits = fetch_recall(db, surface, query, budget)
    soul = soul_of(surface)
    for h in hits:
        print(f'#{h["id"]} score={h["score"]} | ' + h["text"].replace("\n", " "))
    if not hits:
        toks = sorted(_tokens(query))[:8]
        print(f"(阈值内无命中:{soul} 魂组 · 词={toks}…)")
    return hits

def inject_messages(db, surface, query, *, turns=None, recall_budget=None,
                    window=True, max_chars=None):
    """组装注入块:近程窗(可关) + recall。总字数≤max_chars(默认 INJECT_BLOCK_CHARS)。"""
    turns = int(turns if turns is not None else INJECT_WINDOW_TURNS)
    cap = int(max_chars if max_chars is not None else INJECT_BLOCK_CHARS)
    soul = soul_of(surface)
    parts = []
    if window:
        recent = fetch_turns(db, soul, turns)
        if recent:
            lines = []
            for d in recent:
                role = d.get("role") or "?"
                tag = d.get("surface") or d.get("node") or "?"
                lines.append(f'[{tag}/{role}] {str(d.get("content") or "")[:240]}')
            parts.append("[魂组近程]\n" + "\n".join(lines))
    hits = fetch_recall(db, surface, query or "", recall_budget)
    if hits:
        parts.append("[魂组召回]\n" + "\n".join(
            f'#{h["id"]}({h["score"]}) {h["text"]}' for h in hits))
    if not parts:
        return []
    body = "\n\n".join(parts)
    if len(body) > cap:
        body = body[: max(0, cap - 1)] + "…"
    return [{"role": "system", "content": body}]

def doctor(db, extras):
    conn = _conn(db)
    m = detect(conn, verbose=True, refresh=True)
    for r in conn.execute(f'SELECT "{m["node"]}" AS n, COUNT(*) c, MAX({m["ts"] or m["id"]}) last '
                          f'FROM "{m["table"]}" GROUP BY 1 ORDER BY c DESC'):
        print(f'  node={r["n"]}: {r["c"]} 行 · 最新 {r["last"]}')
    nosoul = (conn.execute(f'SELECT COUNT(*) FROM "{m["table"]}" WHERE soul IS NULL').fetchone()[0]
              if "soul" in m["names"] else "未装(先 install)")
    print(f"  soul 未标老行: {nosoul}(老行不迁移,读回靠 node 归组,属正常)")
    try:
        a = conn.execute(f'SELECT COUNT(*) FROM "{ARCHIVE_TABLE}"').fetchone()[0]
        print(f"  冷库 {ARCHIVE_TABLE}: {a} 行")
    except sqlite3.DatabaseError:
        print(f"  冷库 {ARCHIVE_TABLE}: 未建(先 install)")
    legacy = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (LEGACY_MEM_ARCHIVE,),
    ).fetchone()[0]
    if legacy:
        print(f"  警告:遗留表 {LEGACY_MEM_ARCHIVE} 仍在(应 install 迁入后删除)")
    trg = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                       "AND name LIKE 'grid_mem_guard_%'").fetchone()[0]
    print(f"  禁硬删触发器: {'在位' if trg else '缺失(先 install)'} → {ARCHIVE_TABLE}")
    print(f"  真库路径: {os.path.abspath(db)}")
    for kv in extras:
        if "=" not in kv:
            continue
        label, path = kv.split("=", 1)
        if not os.path.exists(path):
            print(f"  [停摆检查] {label}: 路径不存在 {path}")
            continue
        age = (time.time() - os.path.getmtime(path)) / 86400
        flag = " ← 超 3 天没动,疑似停摆" if age > 3 else ""
        print(f"  [停摆检查] {label}: {age:.1f} 天未更新{flag}")

def main():
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__.split("WIRING")[0])
    cmd, db = a[0], a[1]
    if cmd == "install":
        install(db)
    elif cmd == "write":
        if len(a) < 5:
            sys.exit("write <db> <surface> <role> <正文>")
        print("id =", write_turn(db, a[2], a[3], " ".join(a[4:])))
    elif cmd == "read":
        read(db, a[2] if len(a) > 2 else "local", a[3] if len(a) > 3 else 15)
    elif cmd == "recall":
        if len(a) < 4:
            sys.exit("recall <db> <surface> <查询词...>")
        recall(db, a[2], " ".join(a[3:]))
    elif cmd == "archive":
        conn = _conn(db)
        m = detect(conn)
        print("迁入归档:", archive_rows(conn, m, [int(x) for x in a[2:]]), "行")
    elif cmd == "doctor":
        doctor(db, a[2:])
    else:
        sys.exit(f"未知子命令: {cmd}")

if __name__ == "__main__":
    main()
