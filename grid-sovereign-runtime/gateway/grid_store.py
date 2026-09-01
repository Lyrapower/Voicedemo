#!/usr/bin/env python3
"""
grid_store.py — Grid gateway 扩展: 对话归Grid管 + daemon事件回传
挂进现有 FastAPI gateway (8501), 场域app与daemon共用。

设计:
  - 核心 GridStore 零框架依赖 (纯 sqlite3), 可单测可复用
  - FastAPI 路由是薄壳, 底部 build_router() 挂载
  - 单库单文件 grid_store.db, 与你的 JSONL 审计哲学一致: 一切可查

接入 (gateway 主文件加三行):
    from grid_store import build_router
    app.include_router(build_router("grid_store.db"))
    # CORS: 若 app 尚未放行, 加 CORSMiddleware(allow_origins=[...])

daemon 侧回传 (aigc_daemon 等, 6行):
    def emit(kind, **payload):
        try:
            urllib.request.urlopen(urllib.request.Request(
                os.environ.get("GRID_EVENTS", "http://127.0.0.1:8501/store/events"),
                data=json.dumps({"source": "aigc_daemon", "kind": kind,
                                 "payload": payload}).encode(),
                headers={"Content-Type": "application/json"}), timeout=3)
        except Exception:
            pass  # 回传失败不阻塞主流程

鉴权: 环境变量 GRID_STORE_TOKEN 设置后, 所有请求需带
      X-Grid-Token 头。不设则LAN裸信任 (Tailscale内网可接受)。
"""

import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

_DEMO_ROOT = Path(__file__).resolve().parents[2]
if str(_DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEMO_ROOT))
try:
    from grid_mem import (  # noqa: E402
        archive_rows,
        detect,
        soul_of,
        write_turn,
        _CONN_META,
        _gm_set,
    )
except Exception:  # install 前 / 路径漂移时 store 仍可写旧列
    archive_rows = detect = soul_of = write_turn = None  # type: ignore
    _CONN_META = {}  # type: ignore
    _gm_set = None  # type: ignore

_NODE_SURFACE_FALLBACK = {
    "workbench-b11": "b11-home",  # STUDIO 无独立发送面;默认归 home
    "field-particle": "8790",
    "field-compile": "8790",
    "cloud-glm52": "cloud-glm",
    "cloud-kimi": "cloud-kimi",
    "cloud-deepseek": "cloud-deepseek",
    "cloud-qwen35": "cloud-qwen35",
    "cloud-kimi-k3": "cloud-kimi-k3",
    "cloud-glm53": "cloud-glm53",
    "cloud-glm53-full": "cloud-glm53-full",
    "cloud-minimax": "cloud-minimax",
    "cloud": "console-cloud",
}

# ─────────────────────────────────────────────
# 核心存储 — 无框架依赖
# ─────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id TEXT NOT NULL,
  role    TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
  content TEXT NOT NULL,
  ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_node ON messages(node_id, id);

-- 冷记忆:epoch 轮转时从 messages 迁入,禁止硬删生产对话正文
CREATE TABLE IF NOT EXISTS messages_archive(
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id     TEXT NOT NULL,
  role        TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
  content     TEXT NOT NULL,
  ts          REAL NOT NULL,
  archived_at REAL NOT NULL,
  origin_id   INTEGER,
  row_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_msg_arch_node ON messages_archive(node_id, ts, id);

CREATE TABLE IF NOT EXISTS events(
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  source  TEXT NOT NULL,
  kind    TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evt_id ON events(id);
CREATE INDEX IF NOT EXISTS idx_evt_dedup ON events(source, kind, json_extract(payload, '$.date'));
"""

WORKBENCH_B11_NODE = "workbench-b11"
# epoch purge 对这些 node 只迁冷库、永不 DELETE 正文(2026-08-02 事故:硬删后 after_turn 仅 hash 不可恢复)
ARCHIVE_ON_PURGE_NODES = frozenset({
    WORKBENCH_B11_NODE,
    "cloud-glm52",
    "cloud-kimi",
    "cloud-deepseek",
    "cloud-qwen35",
    "cloud-kimi-k3",
    "cloud-glm53",
    "cloud-glm53-full",
    "cloud-minimax",
    "field-particle",
    "field-compile",
})
_TOKEN_FILE = Path(__file__).resolve().parents[1] / "config" / "grid_store.token"


def store_auth_status() -> str:
    """Return store_auth mode for health — on when GRID_STORE_TOKEN loaded."""
    tok = (os.environ.get("GRID_STORE_TOKEN") or "").strip()
    if not tok and _TOKEN_FILE.is_file():
        tok = _TOKEN_FILE.read_text(encoding="utf-8").strip()
    return "on" if tok else "off"


def log_store_auth_banner() -> None:
    if store_auth_status() == "on":
        print("[OK] STORE AUTH: ON", flush=True)
    else:
        print("[WARN] STORE AUTH: OFF — LAN open trust", flush=True)


class WorkbenchB11ProtectedError(ValueError):
    """Raised when a request would delete current-epoch workbench-b11 chat."""


def assert_workbench_b11_purge_allowed(before_ts: float) -> None:
    """Only epoch rollover may purge workbench-b11 (ts strictly before epoch start)."""
    try:
        from field_lane.lane import epoch_start_ts
    except ModuleNotFoundError:
        import datetime as dt
        import os

        anchor_raw = os.environ.get("FIELD_MEMORY_EPOCH_ANCHOR", "2026-07-16")[:10]
        epoch_days = max(1, int(os.environ.get("FIELD_MEMORY_EPOCH_DAYS", os.environ.get("FIELD_MEMORY_DAYS", "7")) or 7))
        try:
            anchor = dt.date.fromisoformat(anchor_raw)
        except ValueError:
            anchor = dt.date(2026, 7, 16)
        today = dt.date.today()
        if today < anchor:
            start = anchor
        else:
            idx = (today - anchor).days // epoch_days
            start = anchor + dt.timedelta(days=idx * epoch_days)

        def epoch_start_ts(*, today: dt.date | None = None) -> float:
            day = today or dt.date.today()
            if day < anchor:
                cur = anchor
            else:
                idx = (day - anchor).days // epoch_days
                cur = anchor + dt.timedelta(days=idx * epoch_days)
            return dt.datetime.combine(cur, dt.time.min).timestamp()

    epoch = epoch_start_ts()
    if before_ts > epoch + 1.0:
        raise WorkbenchB11ProtectedError(
            f"workbench-b11 RED LINE: purge refused (before_ts={before_ts} > epoch_start={epoch})"
        )


DEDUP_KINDS = frozenset({
    "aether_brief",
    "aether_brief_dryrun",
    "aether_paper_daily",
    "aether_premarket_grid",
    "aether_premarket_sonnet",
    "aether_sonnet_earnings",
})

class GridStore:
    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")   # 读写并发不互卡
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    # ── 对话 ──
    def append_messages(self, node_id: str, msgs: list[dict]) -> int:
        """落库。有 surface 时走 grid_mem.write_turn(soul/surface/substrate);
        无 surface 时按 node 推断面,仍写三字段。"""
        with self.lock:
            if write_turn is not None:
                db_path = str(Path(self.db.execute("PRAGMA database_list").fetchone()[2] or "")
                              or (_DEMO_ROOT / "grid-sovereign-runtime" / "data" / "grid_store.db"))
                if self.db.row_factory is None:
                    self.db.row_factory = sqlite3.Row
                _CONN_META[id(self.db)] = {"key": os.path.abspath(db_path), "m": None}
                last = 0
                for m in msgs:
                    surface = (m.get("surface") or _NODE_SURFACE_FALLBACK.get(node_id)
                               or ("cloud-glm" if str(node_id).startswith("cloud") else "grid-app"))
                    last = write_turn(
                        self.db,
                        surface,
                        m["role"],
                        m["content"],
                        substrate=m.get("substrate"),
                        node_id=node_id,
                    )
                return int(last or 0)
            self.db.executemany(
                "INSERT INTO messages(node_id, role, content, ts) VALUES(?,?,?,?)",
                [(node_id, m["role"], m["content"], m.get("ts", time.time()))
                 for m in msgs])
            self.db.commit()
            return self.db.execute("SELECT MAX(id) FROM messages").fetchone()[0]

    def get_messages(
        self,
        node_id: str,
        limit: int = 200,
        before: int | None = None,
        since_ts: float | None = None,
    ):
        q = "SELECT id, role, content, ts FROM messages WHERE node_id=?"
        args: list = [node_id]
        if since_ts is not None:
            q += " AND ts>=?"
            args.append(since_ts)
        if before:
            q += " AND id<?"; args.append(before)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        rows = self.db.execute(q, args).fetchall()[::-1]   # 返回按时间正序
        return [{"id": r[0], "role": r[1], "content": r[2], "ts": r[3]} for r in rows]

    def purge_messages_before(self, node_id: str, before_ts: float, *, hard: bool = False) -> int:
        """Remove messages with ts < before_ts from the hot table.

        Production chat nodes (b11 / cloud-* / field-*): MOVE into messages_archive
        unless hard=True (only for explicit user「清场」).
        Other nodes (e.g. smoke_node): hard DELETE (legacy).
        workbench-b11: hard never allowed via API for current-epoch wipe (RED LINE).
        """
        if node_id == WORKBENCH_B11_NODE:
            assert_workbench_b11_purge_allowed(before_ts)
            if hard:
                # 即使显式 hard, b11 也只允许迁冷库,禁止销毁正文
                hard = False
        with self.lock:
            rows = self.db.execute(
                "SELECT id, role, content, ts FROM messages WHERE node_id=? AND ts<?",
                (node_id, before_ts),
            ).fetchall()
            if not rows:
                return 0
            # 唯一冷库 messages_archive:grid_mem.archive_rows 写入后触发器才放行 DELETE
            if archive_rows is not None and detect is not None:
                db_path = str(Path(self.db.execute("PRAGMA database_list").fetchone()[2] or "")
                              or (_DEMO_ROOT / "grid-sovereign-runtime" / "data" / "grid_store.db"))
                if self.db.row_factory is None:
                    self.db.row_factory = sqlite3.Row
                _CONN_META[id(self.db)] = {"key": os.path.abspath(db_path), "m": None}
                m = detect(self.db)
                archive_rows(self.db, m, [int(r[0]) for r in rows])
            elif (not hard) and node_id in ARCHIVE_ON_PURGE_NODES:
                # grid_mem 未装时的降级:仍写 messages_archive(无 row_json)
                now = time.time()
                self.db.executemany(
                    "INSERT INTO messages_archive(node_id, role, content, ts, archived_at, origin_id) "
                    "VALUES (?,?,?,?,?,?)",
                    [(node_id, r[1], r[2], r[3], now, r[0]) for r in rows],
                )
            cur = self.db.execute(
                "DELETE FROM messages WHERE node_id=? AND ts<?",
                (node_id, before_ts),
            )
            self.db.commit()
            return cur.rowcount

    def get_archived_messages(
        self,
        node_id: str,
        limit: int = 500,
        before: int | None = None,
        since_ts: float | None = None,
    ):
        q = "SELECT id, role, content, ts, archived_at, origin_id FROM messages_archive WHERE node_id=?"
        args: list = [node_id]
        if since_ts is not None:
            q += " AND ts>=?"
            args.append(since_ts)
        if before:
            q += " AND id<?"
            args.append(before)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = self.db.execute(q, args).fetchall()[::-1]
        return [
            {
                "id": r[0],
                "role": r[1],
                "content": r[2],
                "ts": r[3],
                "archived_at": r[4],
                "origin_id": r[5],
                "layer": "archive",
            }
            for r in rows
        ]

    def archive_count(self, node_id: str) -> int:
        with self.lock:
            return int(
                self.db.execute(
                    "SELECT COUNT(*) FROM messages_archive WHERE node_id=?",
                    (node_id,),
                ).fetchone()[0]
            )

    def list_nodes(self):
        rows = self.db.execute(
            "SELECT node_id, COUNT(*), MAX(ts) FROM messages GROUP BY node_id").fetchall()
        return [{"node_id": r[0], "count": r[1], "last_ts": r[2]} for r in rows]

    # ── 事件 ──
    def append_event(self, source: str, kind: str, payload: dict) -> int:
        dedup_date = payload.get("date") if isinstance(payload.get("date"), str) else None
        with self.lock:
            if dedup_date and kind in DEDUP_KINDS:
                row = self.db.execute(
                    "SELECT id FROM events WHERE source=? AND kind=? "
                    "AND json_extract(payload, '$.date')=? ORDER BY id DESC LIMIT 1",
                    (source, kind, dedup_date),
                ).fetchone()
                if row:
                    eid = row[0]
                    self.db.execute(
                        "UPDATE events SET payload=?, ts=? WHERE id=?",
                        (json.dumps(payload, ensure_ascii=False), time.time(), eid),
                    )
                    self.db.commit()
                    return eid
            cur = self.db.execute(
                "INSERT INTO events(source, kind, payload, ts) VALUES(?,?,?,?)",
                (source, kind, json.dumps(payload, ensure_ascii=False), time.time()))
            self.db.commit()
            return cur.lastrowid

    def get_events_by_date(self, source: str, kind: str, trade_date: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, source, kind, payload, ts FROM events "
            "WHERE source=? AND kind=? AND json_extract(payload, '$.date')=? "
            "ORDER BY id DESC",
            (source, kind, trade_date),
        ).fetchall()
        return [{"id": r[0], "source": r[1], "kind": r[2],
                 "payload": json.loads(r[3]), "ts": r[4]} for r in rows]

    def dedup_events_by_date(self, source: str, kind: str) -> dict[str, int]:
        """Remove duplicate rows keeping newest id per payload.date."""
        with self.lock:
            rows = self.db.execute(
                "SELECT id, json_extract(payload, '$.date') AS d FROM events "
                "WHERE source=? AND kind=? AND json_extract(payload, '$.date') IS NOT NULL "
                "ORDER BY id DESC",
                (source, kind),
            ).fetchall()
            seen: set[str] = set()
            deleted = 0
            for eid, d in rows:
                if not d:
                    continue
                if d in seen:
                    self.db.execute("DELETE FROM events WHERE id=?", (eid,))
                    deleted += 1
                else:
                    seen.add(d)
            self.db.commit()
            return {"kind": kind, "deleted": deleted, "kept_dates": len(seen)}

    def get_events(self, since: int = 0, limit: int = 100, source: str | None = None):
        if source:
            rows = self.db.execute(
                "SELECT id, source, kind, payload, ts FROM events "
                "WHERE id>? AND source=? ORDER BY id DESC LIMIT ?",
                (since, source, limit)).fetchall()
        else:
            rows = self.db.execute(
                "SELECT id, source, kind, payload, ts FROM events "
                "WHERE id>? ORDER BY id DESC LIMIT ?", (since, limit)).fetchall()
        return [{"id": r[0], "source": r[1], "kind": r[2],
                 "payload": json.loads(r[3]), "ts": r[4]} for r in rows]

    def get_events_snapshot(self, source: str, kinds: list[str] | None = None):
        """每种 kind 最新一条 — 避免 paper_wallet 心跳淹没 brief/scan。"""
        if kinds:
            placeholders = ",".join("?" * len(kinds))
            rows = self.db.execute(
                f"""
                SELECT e.id, e.source, e.kind, e.payload, e.ts
                FROM events e
                INNER JOIN (
                    SELECT kind, MAX(id) AS max_id
                    FROM events WHERE source=? AND kind IN ({placeholders})
                    GROUP BY kind
                ) latest ON e.id = latest.max_id
                WHERE e.source=?
                ORDER BY e.id DESC
                """,
                (source, *kinds, source),
            ).fetchall()
        else:
            rows = self.db.execute(
                """
                SELECT e.id, e.source, e.kind, e.payload, e.ts
                FROM events e
                INNER JOIN (
                    SELECT kind, MAX(id) AS max_id
                    FROM events WHERE source=?
                    GROUP BY kind
                ) latest ON e.id = latest.max_id
                WHERE e.source=?
                ORDER BY e.id DESC
                """,
                (source, source),
            ).fetchall()
        return [{"id": r[0], "source": r[1], "kind": r[2],
                 "payload": json.loads(r[3]), "ts": r[4]} for r in rows]

    def get_events_recent_by_kinds(
        self, source: str, kinds: list[str], per_kind: int = 15,
    ):
        """每种 kind 最近 N 条 — brief / premarket 历史列表用。"""
        out = []
        for kind in kinds:
            rows = self.db.execute(
                "SELECT id, source, kind, payload, ts FROM events "
                "WHERE source=? AND kind=? ORDER BY id DESC LIMIT ?",
                (source, kind, per_kind),
            ).fetchall()
            for r in rows:
                out.append({
                    "id": r[0], "source": r[1], "kind": r[2],
                    "payload": json.loads(r[3]), "ts": r[4],
                })
        out.sort(key=lambda e: e["id"], reverse=True)
        return out

# ─────────────────────────────────────────────
# FastAPI 薄壳 — 挂载到现有 gateway
# ─────────────────────────────────────────────

def build_router(db_path: str = "grid_store.db"):
    from fastapi import APIRouter, Request, HTTPException

    store = GridStore(db_path)
    token = os.environ.get("GRID_STORE_TOKEN", "")
    bridge_token = os.environ.get("BRIDGE_STORE_TOKEN", "")
    r = APIRouter(prefix="/store", tags=["store"])

    def gate(req: Request):
        if token and req.headers.get("X-Grid-Token") != token:
            raise HTTPException(401, "bad or missing X-Grid-Token")

    def gate_emit(req: Request):
        hdr = req.headers.get("X-Grid-Token")
        if token and hdr != token:
            if not (bridge_token and hdr == bridge_token):
                raise HTTPException(401, "bad or missing X-Grid-Token")

    @r.get("/conversations")
    async def nodes(req: Request):
        gate(req)
        return store.list_nodes()

    @r.get("/conversations/{node_id}")
    async def history(
        node_id: str,
        req: Request,
        limit: int = 200,
        before: int | None = None,
        since_ts: float | None = None,
    ):
        gate(req)
        return store.get_messages(node_id, limit, before, since_ts)

    @r.get("/conversations/{node_id}/archive")
    async def history_archive(
        node_id: str,
        req: Request,
        limit: int = 500,
        before: int | None = None,
        since_ts: float | None = None,
    ):
        """Cold memory (epoch-rolled). Never hard-deleted for ARCHIVE_ON_PURGE_NODES."""
        gate(req)
        return {
            "node_id": node_id,
            "count": store.archive_count(node_id),
            "messages": store.get_archived_messages(node_id, limit, before, since_ts),
        }

    @r.post("/conversations/{node_id}/purge")
    async def purge_messages(node_id: str, req: Request):
        gate(req)
        body = await req.json()
        before_ts = body.get("before_ts")
        if not isinstance(before_ts, (int, float)):
            raise HTTPException(422, "before_ts (number) required")
        hard = bool(body.get("hard"))
        try:
            deleted = store.purge_messages_before(node_id, float(before_ts), hard=hard)
        except WorkbenchB11ProtectedError as exc:
            raise HTTPException(403, str(exc)) from exc
        # b11 强制 archive; 其它生产 node 默认 archive, hard 仅清场
        archived = (node_id in ARCHIVE_ON_PURGE_NODES) and not (
            hard and node_id != WORKBENCH_B11_NODE
        )
        if node_id == WORKBENCH_B11_NODE:
            archived = True
        return {
            "node_id": node_id,
            "before_ts": float(before_ts),
            "deleted": deleted,
            "moved_to_archive": deleted if archived else 0,
            "mode": "archive" if archived else "hard_delete",
            "hard": hard and not archived,
        }

    @r.post("/conversations/{node_id}/messages")
    async def append(node_id: str, req: Request):
        gate(req)
        body = await req.json()
        msgs = body if isinstance(body, list) else [body]
        for m in msgs:
            if m.get("role") not in ("user", "assistant", "system") \
               or not isinstance(m.get("content"), str):
                raise HTTPException(422, "each message needs role+content")
        return {"last_id": store.append_messages(node_id, msgs)}

    @r.get("/soul/{soul}/inject")
    async def soul_inject(soul: str, req: Request, q: str = "", surface: str = "", n: int = 15):
        """魂组 read+recall 注入块(供 grid.html / 旁路组装 prompt;不经 node 切分)。"""
        gate(req)
        if soul not in ("local", "cloud"):
            raise HTTPException(422, "soul must be local or cloud")
        try:
            from grid_mem import DEFAULT_STORE_DB, inject_messages
            db = os.environ.get("GRID_STORE_DB") or str(
                _DEMO_ROOT / "grid-sovereign-runtime" / "data" / "grid_store.db"
            )
            if not surface:
                surface = "cloud-glm" if soul == "cloud" else "grid-app"
            msgs = inject_messages(db, surface, q or "", turns=n)
            return {"soul": soul, "surface": surface, "messages": msgs}
        except Exception as exc:
            raise HTTPException(500, f"soul inject failed: {exc}") from exc

    @r.post("/events")
    async def emit(req: Request):
        gate_emit(req)
        b = await req.json()
        if not b.get("source") or not b.get("kind"):
            raise HTTPException(422, "source and kind required")
        return {"id": store.append_event(b["source"], b["kind"],
                                         b.get("payload", {}))}

    @r.get("/events")
    async def feed(req: Request, since: int = 0, limit: int = 100, source: str | None = None):
        gate(req)
        return store.get_events(since, limit, source)

    @r.get("/events/snapshot")
    async def feed_snapshot(req: Request, source: str = "aether", kinds: str | None = None):
        """每种 kind 最新一条 — 页面 TRADING 回填用, 不被 paper 心跳挤掉。"""
        gate(req)
        kind_list = [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None
        return store.get_events_snapshot(source, kind_list)

    @r.get("/events/recent")
    async def feed_recent(
        req: Request,
        source: str = "aether",
        kinds: str = "aether_brief,aether_premarket,aether_premarket_grid,aether_premarket_sonnet",
        per_kind: int = 15,
    ):
        """每种 kind 最近 N 条 — 盘前 / 过往简报。"""
        gate(req)
        kind_list = [k.strip() for k in kinds.split(",") if k.strip()]
        return store.get_events_recent_by_kinds(source, kind_list, per_kind)

    @r.get("/fleet")
    async def fleet(req: Request):
        """舰队状态透传: exporter (ledger) 生成的 fleet_status.json 经 gateway 供给
        dashboard 与手机端。gateway 只转不算 — clean-days 的事实源仍是 ledger。"""
        gate(req)
        p = Path(os.environ.get("FLEET_STATUS", "fleet_status.json"))
        if not p.exists():
            raise HTTPException(404, "fleet_status.json not generated yet")
        return json.loads(p.read_text(encoding="utf-8"))

    @r.get("/pipeline/health")
    async def pipeline_health_route(req: Request):
        """Aether compile lanes — last success/failure timestamps."""
        gate(req)
        import importlib

        aether_dir = Path(__file__).resolve().parents[2] / "aether_nexus"
        if str(aether_dir) not in sys.path:
            sys.path.insert(0, str(aether_dir))
        ph_mod = importlib.import_module("pipeline_health")
        importlib.reload(ph_mod)

        return ph_mod.pipeline_health()

    @r.get("/report/daily/{trade_date}")
    async def daily_report(trade_date: str, req: Request):
        """C5 — full brief + paper daily for a trade date."""
        gate(req)
        briefs = store.get_events_by_date("aether", "aether_brief", trade_date)
        dry = store.get_events_by_date("aether", "aether_brief_dryrun", trade_date)
        paper = store.get_events_by_date("aether", "aether_paper_daily", trade_date)
        return {
            "date": trade_date,
            "brief": briefs[0] if briefs else None,
            "brief_dryrun": dry[0] if dry else None,
            "paper_daily": paper[0] if paper else None,
        }

    @r.post("/events/dedup")
    async def dedup_events(req: Request):
        """B2 cleanup — collapse duplicate events by payload.date per kind."""
        gate(req)
        body = await req.json()
        kinds = body.get("kinds") or list(DEDUP_KINDS)
        source = body.get("source") or "aether"
        return [store.dedup_events_by_date(source, k) for k in kinds]

    @r.get("/field/history")
    async def field_history(req: Request, lane: str = "all", limit: int = 200):
        """Unified app/8790 memory lanes (field-particle / field-compile)."""
        gate(req)
        _root = Path(__file__).resolve().parents[1]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from field_lane.lane import NODE_CHAT, NODE_COMPILE, epoch_start_ts

        since = epoch_start_ts()
        out: dict = {}
        if lane in ("all", "chat"):
            out["chat"] = {
                "node_id": NODE_CHAT,
                "messages": store.get_messages(NODE_CHAT, limit, since_ts=since),
            }
        if lane in ("all", "compile"):
            out["compile"] = {
                "node_id": NODE_COMPILE,
                "messages": store.get_messages(NODE_COMPILE, limit, since_ts=since),
            }
        return out

    @r.post("/field/after_turn")
    async def field_after_turn(req: Request):
        """App / sidecar: archive + auto-distill after a completed turn."""
        gate(req)
        body = await req.json()
        instruction = str(body.get("instruction") or "").strip()
        draft = str(body.get("draft") or "").strip()
        task = str(body.get("task") or "chat")
        node_id = str(body.get("node_id") or "").strip()
        persona = body.get("persona")
        client = str(body.get("client") or "app")
        auto_coach = body.get("auto_coach", True)
        schema = body.get("schema")
        compile_semantics = body.get("compile_semantics")
        test = body.get("test")
        if not draft:
            raise HTTPException(422, "draft required")
        _root = Path(__file__).resolve().parents[1]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from field_lane.lane import TASK_BUDGETS, classify_task, node_for_task
        from field_lane.distill import schedule_after_turn
        from field_lane.schema import COMPILE_SEMANTICS_PARSE_ONLY, SCHEMA_LOOSE

        hint = task if task in TASK_BUDGETS else None
        task_resolved = classify_task(instruction, hint)
        if not node_id:
            node_id = node_for_task(task_resolved)
        schema_resolved = str(schema).strip() if schema else None
        semantics_resolved = str(compile_semantics).strip() if compile_semantics else None
        if not semantics_resolved and task_resolved in ("compile_json", "handoff_protocol"):
            schema_resolved = schema_resolved or SCHEMA_LOOSE
            semantics_resolved = COMPILE_SEMANTICS_PARSE_ONLY
        schedule_after_turn(
            instruction,
            draft,
            task=task_resolved,
            node_id=node_id,
            persona=str(persona) if persona else None,
            client=client,
            auto_coach=bool(auto_coach),
            schema=schema_resolved,
            compile_semantics=semantics_resolved,
            test=bool(test) if test is not None else None,
        )
        return {
            "queued": True,
            "node_id": node_id,
            "task": task_resolved,
            "auto_coach": bool(auto_coach),
            "schema": schema_resolved,
            "compile_semantics": semantics_resolved,
        }

    @r.post("/field/coach")
    async def field_coach(req: Request):
        """Explicit Fable coach — manual zone; does not require compile auto-trigger."""
        gate(req)
        body = await req.json()
        instruction = str(body.get("instruction") or "").strip()
        draft = str(body.get("draft") or "").strip()
        task = str(body.get("task") or "compile_json")
        node_id = str(body.get("node_id") or "").strip()
        persona = body.get("persona")
        client = str(body.get("client") or "app")
        allow_draft = bool(body.get("allow_draft"))
        compile_semantics = body.get("compile_semantics")
        test = body.get("test")
        if not draft:
            raise HTTPException(422, "draft required")
        _root = Path(__file__).resolve().parents[1]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from field_lane.lane import TASK_BUDGETS, classify_task, node_for_task
        from field_lane.distill import schedule_coach, should_distill

        hint = task if task in TASK_BUDGETS else None
        task_resolved = classify_task(instruction or draft, hint)
        if not node_id:
            node_id = node_for_task(task_resolved)

        if body.get("sync"):
            import asyncio
            from field_lane.distill_api import run_coach_sync

            result = await asyncio.to_thread(
                run_coach_sync,
                instruction=instruction or draft,
                draft=draft,
                task=task_resolved,
                node_id=node_id,
                client=client,
                persona=str(persona) if persona else None,
                force=True,
                compile_semantics=str(compile_semantics).strip() if compile_semantics else None,
                allow_draft=allow_draft,
                test=bool(test) if test is not None else None,
            )
            return result

        schedule_coach(
            instruction or draft,
            draft,
            task=task_resolved,
            node_id=node_id,
            persona=str(persona) if persona else None,
            client=client,
            compile_semantics=str(compile_semantics).strip() if compile_semantics else None,
            allow_draft=allow_draft,
            test=bool(test) if test is not None else None,
        )
        return {
            "queued": True,
            "coach": True,
            "node_id": node_id,
            "task": task_resolved,
            "auto_eligible": should_distill(task_resolved),
        }

    @r.get("/distill/inbox")
    async def distill_inbox(
        req: Request,
        filter: str = "pending",
        date: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ):
        gate(req)
        _root = Path(__file__).resolve().parents[1]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from field_lane.distill_api import inbox_list

        return inbox_list(status_filter=filter, on_date=date, limit=limit, offset=offset)

    @r.get("/distill/queue")
    async def distill_queue(req: Request, status: str = "pending", date: str | None = None, limit: int = 50):
        gate(req)
        _root = Path(__file__).resolve().parents[1]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from field_lane.distill_api import list_queue

        return {"rows": list_queue(status=status, on_date=date, limit=limit)}

    @r.get("/distill/record/{record_id}")
    async def distill_record(record_id: str, req: Request):
        gate(req)
        _root = Path(__file__).resolve().parents[1]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from field_lane.distill_api import get_record_detail

        row = get_record_detail(record_id)
        if not row:
            raise HTTPException(404, "record not found")
        return row

    @r.get("/distill/recent")
    async def distill_recent(req: Request, limit: int = 10, date: str | None = None):
        gate(req)
        _root = Path(__file__).resolve().parents[1]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from field_lane.distill_api import recent_records

        return {"records": recent_records(limit=limit, on_date=date)}

    @r.get("/distill/latest_compile")
    async def distill_latest_compile(req: Request):
        gate(req)
        _root = Path(__file__).resolve().parents[1]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from field_lane.distill_api import latest_compile_pair

        return latest_compile_pair()

    @r.get("/distill/stats")
    async def distill_stats(req: Request, date: str | None = None):
        gate(req)
        _root = Path(__file__).resolve().parents[1]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from field_lane.review_state import stats_summary

        return stats_summary(on_date=date)

    @r.post("/distill/review")
    async def distill_review(req: Request):
        gate(req)
        body = await req.json()
        record_id = str(body.get("record_id") or "").strip()
        status = str(body.get("status") or "").strip()
        reason = str(body.get("reason") or "").strip()
        via = str(body.get("via") or "tab3")
        if not record_id or not status:
            raise HTTPException(422, "record_id and status required")
        _root = Path(__file__).resolve().parents[1]
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from field_lane.distill_api import post_review

        try:
            return post_review(record_id, status, reason=reason, via=via)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    return r
