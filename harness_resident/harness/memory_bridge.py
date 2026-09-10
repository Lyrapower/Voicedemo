"""Harness → 8501 store memory bridge (REVIEW v1.6 + Astra).

Writes ONLY `harness-shared`. Lane nodes are read-only.
Backfill / live deliver is idempotent on (receipt_id, dest, projection_version).
Does not write field-particle / diary / workbench-b11 / cloud-* production lanes.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECTION_VERSION = "v1"
SHARED_NODE = "harness-shared"
SELFTEST_NODE = "harness-shared-selftest"
FORBIDDEN_NODES = ("field-particle", "workbench-b11", "cloud-glm52", "cloud-kimi", "cloud-deepseek")
CARD_PREFIX = "[工作日志]"
SHARED_TITLE = "工作卡·harness-shared"
LANES = ("scout", "research", "builder", "gardener", "rwa")
WORKERS = ("fast", "deep", "full", "research", "local", "cc")
PT = ZoneInfo("America/Los_Angeles")
BACKFILL_SINCE = datetime(2026, 9, 6, tzinfo=PT)

_SIGNAL_RE = re.compile(
    r"(?:做多|做空|买入|卖出|加仓|减仓|清仓|建仓|平仓)"
    r"|(?:\b(?:long|short|buy|sell)\b\s*[:：]?\s*[A-Z]{2,5}\b)"
    r"|(?:入场|进场|目标价|止损|止盈)\s*[:：]\s*\$?\d"
    r"|(?:仓位|position\s*size)\s*[:：]\s*\d+\s*%",
    re.I,
)
_SECRET_RE = re.compile(
    r"(?i)(bearer\s+\S+|sk-[a-z0-9]+|api[_-]?key\s*[:=]\s*\S+|GRID_HARNESS_[A-Z0-9_]+\s*[:=]\s*\S+)"
)


def redact(text: str, limit: int = 240) -> str:
    s = _SECRET_RE.sub("[REDACTED]", str(text or "").replace("\n", " ").strip())
    return s[:limit]


def signal_blocked(text: str) -> bool:
    return bool(_SIGNAL_RE.search(str(text or "")))


def _iso(ts) -> str:
    if ts is None or ts == "":
        return ""
    if isinstance(ts, str):
        return ts
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return str(ts)


def project_work_card(rec: dict[str, Any], *, backfilled: bool = False) -> str | None:
    rid = str(rec.get("receipt_id") or rec.get("event_id") or "").strip()
    mid = str(rec.get("mid") or rec.get("mission_id") or "").strip()
    if not rid or not mid:
        return None
    worker = str(rec.get("worker") or "")
    tags = []
    if worker == "research":
        tags.append("deepseek_inbound")
    else:
        tags.append("worker:" + (worker or "unknown"))
    if backfilled:
        tags.append("backfilled=1")
    if rec.get("test_run_id"):
        tags.append("test_run_id=" + str(rec["test_run_id"]))
    line = (
        f"{CARD_PREFIX} mid={mid} jid={rec.get('jid') or rec.get('job_id') or ''} "
        f"worker={worker} lane={rec.get('lane') or ''} "
        f"model_resolved={rec.get('model_resolved') or ''} "
        f"tools={rec.get('tools') or rec.get('tools_used') or ''} "
        f"result={redact(rec.get('result') or rec.get('conclusion') or rec.get('status') or '')} "
        f"receipt_id={rid} ts={_iso(rec.get('ts'))} {' '.join(tags)}"
    )
    if signal_blocked(line):
        return None
    return line


def project_kind_card(kind: str, rec: dict[str, Any], *, backfilled: bool = False) -> str | None:
    rid = str(rec.get("receipt_id") or rec.get("event_id") or "").strip()
    if not rid:
        return None
    extra = " backfilled=1" if backfilled else ""
    text = redact(rec.get("text") or rec.get("conclusion") or "", 400)
    line = f"[{kind}] mid={rec.get('mid') or rec.get('mission_id') or ''} receipt_id={rid} {text}{extra}"
    if signal_blocked(line):
        return None
    return line


def identity_block(*, local: bool = False) -> str:
    now = datetime.now(PT)
    budget = 2000 if local else 4000
    body = (
        "agents·此刻身份\n"
        f"clock PDT {now.strftime('%Y-%m-%d %H:%M')}\n"
        "ports 8630=harness 8501=gateway+store\n"
        f"lanes {','.join(LANES)} · workers {','.join(WORKERS)}\n"
        "research=DeepSeek · local=9B · deep=scout 决策官 · Grid 是主体且不调度\n"
        "门: money/写宿主/表外出网 出生 BLOCKED；read_only 剥写工具\n"
        "harness-shared 只 harness 写；lane 节点只读\n"
        "本线程未绑 mission_ref 则只可读工具面，不执行"
    )
    return body[:budget]


def tool_surface_block(allowed: list[str] | None = None) -> str:
    rows = [
        "这是你此刻全部工具,表外没有",
        "web.fetch · GET 已登记域名 · ```tool {\"tool\":\"web.fetch\",\"url\":\"https://…\"} · 结果回 prior.status/text",
        "web.search · 检索 · ```tool {\"tool\":\"web.search\",\"q\":\"…\"} · 结果回 prior.hits",
        "grants.catalog · 联邦/州目录 · ```tool {\"tool\":\"grants.catalog\"} · 结果回 prior.rows",
        "本线程只可读,执行请绑 mission",
    ]
    if allowed:
        rows.append("job.allowed_tools " + ",".join(allowed))
    text = "\n".join(rows)
    return text[:1500]


def workcard_block(cards: list[str], *, budget: int = 2000) -> str:
    kept: list[str] = []
    used = 0
    title = SHARED_TITLE + "\n"
    for c in cards:
        add = c.strip()
        if not add:
            continue
        if used + len(add) + 1 > budget:
            kept.append("[截断]")
            break
        kept.append(add)
        used += len(add) + 1
    return title + "\n".join(kept) if kept else ""


class MemoryBridge:
    def __init__(self, store, *, dest: str = SHARED_NODE):
        if dest not in {SHARED_NODE, SELFTEST_NODE}:
            raise ValueError("dest must be harness-shared or selftest")
        self.store = store
        self.dest = dest

    def already(self, receipt_id: str) -> bool:
        row = self.store.get_bridge_outbox(receipt_id, self.dest, PROJECTION_VERSION)
        return bool(row and row.get("status") in {"delivered", "rejected"})

    def offer(self, rec: dict[str, Any], *, kind: str = "工作日志",
              backfilled: bool = False) -> dict[str, Any]:
        if kind == "工作日志":
            card = project_work_card(rec, backfilled=backfilled)
        else:
            card = project_kind_card(kind, rec, backfilled=backfilled)
        rid = str(rec.get("receipt_id") or rec.get("event_id") or "")
        if not rid:
            return {"status": "rejected", "reason": "no_receipt_id"}
        if self.already(rid):
            row = self.store.get_bridge_outbox(rid, self.dest, PROJECTION_VERSION)
            return {"status": "idempotent", "receipt_id": rid, "prior": row.get("status")}
        if card is None:
            self.store.put_bridge_outbox(
                receipt_id=rid, dest=self.dest, projection_version=PROJECTION_VERSION,
                status="rejected", reject_reason="signal_or_incomplete")
            return {"status": "rejected", "receipt_id": rid, "reason": "signal_or_incomplete"}
        self.store.put_bridge_outbox(
            receipt_id=rid, dest=self.dest, projection_version=PROJECTION_VERSION,
            status="pending", card=card)
        ok, err = _append_shared(self.dest, card)
        if ok:
            self.store.mark_bridge_outbox(rid, self.dest, PROJECTION_VERSION, "delivered")
            return {"status": "delivered", "receipt_id": rid}
        self.store.mark_bridge_outbox(rid, self.dest, PROJECTION_VERSION, "pending", err)
        return {"status": "pending", "receipt_id": rid, "reason": err}

    def emit_job(self, job: dict[str, Any], *, status: str, receipt_id: str,
                 error: str = "", model_resolved: str = "") -> dict[str, Any]:
        origin = str(job.get("origin") or "")
        mid = ""
        if origin.startswith("mission:"):
            mid = origin.split(":")[1]
        rec = {
            "receipt_id": receipt_id,
            "event_id": receipt_id,
            "mid": mid or job.get("job_id"),
            "jid": job.get("job_id"),
            "worker": job.get("worker"),
            "lane": job.get("lane"),
            "model_resolved": model_resolved,
            "tools": ",".join(job.get("allowed_tools") or []),
            "result": error or status,
            "status": status,
            "ts": time.time(),
        }
        return self.offer(rec, kind="工作日志")


def _append_shared(node: str, card: str) -> tuple[bool, str]:
    if node not in {SHARED_NODE, SELFTEST_NODE}:
        return False, "dest_not_shared"
    try:
        from . import store_memory
        store_memory.append_messages(node, [{
            "role": "system",
            "content": card,
            "surface": node,
            "substrate": "harness",
        }])
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}:{e}"


def load_shared_cards(*, dest: str = SHARED_NODE, limit: int = 200) -> list[str]:
    try:
        from . import store_memory
        rows = store_memory.get_messages(dest, limit=limit)
    except Exception:
        return []
    out = []
    for row in rows:
        c = str(row.get("content") or "")
        if "test_run_id=" in c:
            continue
        if c.startswith(CARD_PREFIX) or c.startswith("[决定]") or c.startswith("[终判]") \
                or c.startswith("[收口]") or c.startswith("[播种]") or c.startswith("[lane 状态]"):
            out.append(c)
    return out[-20:]


def collect_backfill_records(store, *, since_ts: float | None = None) -> list[dict[str, Any]]:
    since = since_ts if since_ts is not None else BACKFILL_SINCE.timestamp()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    root = Path("state") / "missions"
    if not root.is_dir():
        root = Path(__file__).resolve().parents[1] / "state" / "missions"
    for mid_dir in sorted(root.glob("M-*")):
        mid = mid_dir.name
        p = mid_dir / "receipts.jsonl"
        if not p.is_file():
            continue
        try:
            m = store.get_mission(mid)
        except KeyError:
            m = {"worker": "", "lane": "", "created_at": 0}
        if float(m.get("created_at") or 0) and float(m["created_at"]) < since:
            # still allow if file mtime recent; package says since 09-06
            pass
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = str(rec.get("event_id") or rec.get("action_id") or "")
            ts = rec.get("ts") or rec.get("created_at") or 0
            try:
                ts_f = float(ts)
            except (TypeError, ValueError):
                ts_f = 0
            if ts_f and ts_f < since:
                continue
            if not rid or rid in seen:
                continue
            seen.add(rid)
            out.append({
                "receipt_id": rid,
                "event_id": rid,
                "mid": mid,
                "jid": rec.get("job_id") or "",
                "worker": m.get("worker") or rec.get("worker") or "",
                "lane": m.get("lane") or "",
                "model_resolved": rec.get("model_resolved") or "",
                "result": rec.get("conclusion") or rec.get("status") or "",
                "status": rec.get("status") or "",
                "ts": ts_f or time.time(),
            })
        close = m.get("close_reason")
        if close:
            crid = f"close:{mid}"
            if crid not in seen:
                seen.add(crid)
                out.append({
                    "receipt_id": crid,
                    "event_id": crid,
                    "mid": mid,
                    "kind": "收口",
                    "text": f"close_reason={close}",
                    "worker": m.get("worker") or "",
                    "lane": m.get("lane") or "",
                    "ts": m.get("updated_at") or time.time(),
                })
    return out


CONFIG_DECISIONS = [
    ("decide:worker-deep", "worker 钉 deep · scout 决策官不 fallback"),
    ("decide:universe-global", "宇宙改全球 · Universe v4 / Sources v2"),
    ("decide:cycle-off", "周期 off · 重启看数据源/预算/授权"),
    ("decide:lane-vs-worker", "命名两词分清 · lane=授权 · worker=角色"),
]


def backfill(store, *, dest: str = SHARED_NODE) -> dict[str, Any]:
    br = MemoryBridge(store, dest=dest)
    counts = {"delivered": 0, "idempotent": 0, "rejected": 0, "pending": 0, "close": 0, "decide": 0}
    for rec in collect_backfill_records(store):
        kind = rec.get("kind") or "工作日志"
        r = br.offer(rec, kind=kind, backfilled=True)
        st = r.get("status") or "pending"
        counts[st] = counts.get(st, 0) + 1
        if kind == "收口" and st == "delivered":
            counts["close"] += 1
    for rid, text in CONFIG_DECISIONS:
        r = br.offer({
            "receipt_id": rid, "event_id": rid, "mid": "",
            "text": text, "ts": BACKFILL_SINCE.timestamp(),
        }, kind="决定", backfilled=True)
        if r.get("status") == "delivered":
            counts["decide"] += 1
        elif r.get("status") == "idempotent":
            counts["idempotent"] += 1
    return counts


if __name__ == "__main__":
    import sys
    from .db import Store
    db = Store(str(Path(__file__).resolve().parents[1] / "state" / "harness.db"))
    cmd = sys.argv[1] if len(sys.argv) > 1 else "backfill"
    if cmd == "snapshot":
        print(json.dumps(snapshot_forbidden(), ensure_ascii=False, indent=2))
    else:
        before = snapshot_forbidden()
        counts = backfill(db)
        after = snapshot_forbidden()
        print(json.dumps({"before": before, "counts": counts, "after": after}, ensure_ascii=False, indent=2))


def snapshot_forbidden() -> dict[str, int]:
    """Read-only counts from GET /store/conversations. Never write these nodes."""
    listing = _list_node_counts()
    out = {n: int(listing.get(n, 0)) for n in FORBIDDEN_NODES}
    out["diary"] = _diary_entry_count()
    return out


def _list_node_counts() -> dict[str, int]:
    import json as _json
    import urllib.request
    base = os.environ.get("GRID_STORE_BASE", "http://127.0.0.1:8501").rstrip("/")
    headers = {"Accept": "application/json"}
    tok = (os.environ.get("GRID_STORE_TOKEN") or os.environ.get("BRIDGE_STORE_TOKEN") or "").strip()
    if tok:
        headers["X-Grid-Token"] = tok
    try:
        req = urllib.request.Request(f"{base}/store/conversations", headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode())
    except Exception:
        return {}
    rows = data if isinstance(data, list) else (data.get("nodes") or data.get("conversations") or [])
    out: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        nid = str(row.get("node_id") or row.get("node") or "")
        if nid:
            out[nid] = int(row.get("count") or 0)
    return out


def _diary_entry_count() -> int:
    """Read-only. Never POST /diary."""
    import json as _json
    import urllib.request
    for url in (
        "http://127.0.0.1:8790/diary/integrity",
        "http://127.0.0.1:8790/diary/settings",
    ):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = _json.loads(resp.read().decode())
            if not isinstance(data, dict):
                continue
            for k in ("entries", "entry_count", "n_entries", "count"):
                if k in data:
                    return int(data[k])
            inner = data.get("integrity") or data.get("stats") or {}
            if isinstance(inner, dict):
                for k in ("entries", "entry_count", "n_entries", "count"):
                    if k in inner:
                        return int(inner[k])
        except Exception:
            continue
    return -1


def inject_blocks(*, worker: str = "research", allowed_tools: list[str] | None = None) -> list[dict[str, str]]:
    local = worker == "local"
    cards = load_shared_cards()
    blocks = []
    wc = workcard_block(cards, budget=1000 if local else 2000)
    if wc:
        blocks.append({"role": "system", "content": wc})
    blocks.append({"role": "system", "content": tool_surface_block(allowed_tools)})
    blocks.append({"role": "system", "content": identity_block(local=local)})
    return blocks
