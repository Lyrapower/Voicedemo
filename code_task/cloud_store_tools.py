"""Cloud GLM (侯) · store 原文只读工具 — P1/P2.

三个只读工具,让 GLM 自己查 store 对话原文(不靠 Lyra 转贴):

  store.search(query, limit=5, since=null) → 命中条目原文
  store.recent(days=null, limit=20, start_ts=null, end_ts=null) → 时间范围原文(跨会话事件链)
  store.get(id) → 单条原文

铁则:只读(只读 sqlite 连接)、返回原文不改写、单条上限 ~3k token(6000 字符)超出截断带 [截断]、
每轮调用上限 3、SIGNAL_RE 仅分类(proposal_detected),不删除原文。

边界:日记层(events / grid_diary)不对外开放 —— 工具只查 cloud-* 对话原文(messages + messages_archive)。

文本协议(GLM 在回复里发,executor 解析):
  <<store.search: query="option workflow", limit=5>>
  <<store.recent: days="7", limit="20">>
  <<store.get: id="42">>

不触 8501 gateway 冻结链;不写 cloud-glm52;只读 messages / messages_archive。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

MAX_TOOL_RESULT_CHARS = 6000
MAX_TOOL_CALLS_PER_ROUND = 3
TRUNC_MARK = "[截断]"

_SIGNAL_PATTERNS = [
    r"(?:做多|做空|买入|卖出|加仓|减仓|清仓|建仓|平仓)",
    r"\b(?:long|short|buy|sell)\b\s*[:：]?\s*[A-Z]{2,5}\b",
    r"(?:入场|进场|目标价|止损|止盈)\s*[:：]?\s*\$?\d",
    r"(?:仓位|position\s*size)\s*[:：]?\s*\d+\s*%",
]
SIGNAL_RE = re.compile("|".join(_SIGNAL_PATTERNS), re.I)

_DEMO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_STORE_DB = _DEMO_ROOT / "grid-sovereign-runtime" / "data" / "grid_store.db"


def _store_db_path() -> str:
    p = (os.getenv("GRID_STORE_DB") or "").strip()
    return p if p else str(_DEFAULT_STORE_DB)


TOOL_DECLARATION_TITLE = "工具·store原文 + 跨项目实况(只读·P1+第五节)"

TOOL_DECLARATION = (
    TOOL_DECLARATION_TITLE
    + """

你可以调用只读工具查 store 原文与跨项目实况(不靠 Lyra 转贴)。

铁则:store.search / store.recent / store.get / events.recent / pulse.snapshot / ows.day 是能力,不是许可。
不确定就调。不调就别说"看不到"。说"看不到"之前,先调过。调了没有,就是没有。
涉及过去的事、旧文件、旧版本、"之前"、"上周":先调 store.search 或 store.recent 再答。
涉及某个端口/服务现在通不通:先调 pulse.snapshot 或 ows.day 再答。

在回复里发工具调用,系统执行后把结果喂回你,你再作答。

调用格式(单独一行):
  <<store.search: query="关键词", limit=5>>
  <<store.recent: days="7", limit="20">>
  <<store.recent: start_ts="1690000000", end_ts="1691000000", limit="50">>
  <<store.get: id="42">>
  <<pulse.snapshot: >>
  <<ows.day: date="2026-08-13">>
  <<events.recent: kind="aether_scan", limit="10">>

参数:
  - query:   搜索关键词(匹配正文,大小写不敏感)
  - limit:   返回条数上限(search 默认 5;recent 默认 20;events.recent 上限 20)
  - since:   unix 秒,只返回 ts >= since(search)
  - days:    近 N 日(recent;与 start_ts/end_ts 二选一)
  - start_ts/end_ts: 时间范围 unix 秒(recent;跨会话事件链用这个,按 ts 倒序返回)
  - date:    YYYY-MM-DD(ows.day)
  - kind:    事件 kind,白名单 aether_* / stock_card.v1;grid_diary 等日记类硬拒(events.recent)

三类工具:
  · store.* 查本 lane 对话原文 + harness-shared 工作卡(只读,不写)。单条超 ~3k token 截断带 [截断],用 store.get(id) 拉全文。时间窗按 PDT 日历日,不是裸 unix 秒。
  · pulse.snapshot 取 alpha 8600 热力面排序 + 健康灯(剥 raw rows,只引数字不引结论)。
  · ows.day 取 OWS 8620 单日 GEX/IVP;net=0 或 IV30 缺时显式标"参考不可信"(Theta FREE OI=0 同族)。
  · events.recent 取 8501 events 表最近 N 条;日记类(grid_diary)硬拒。

返回内容照过 SIGNAL_RE(命中交易信号 → 拦截标记)。
规则:每轮最多调 3 次;工具结果以 <<tool_result>> 块喂回;找不到就说找不到,不要伪造;日记层不对外开放。
"""
)

_TOOL_CALL_RE = re.compile(
    r"<<\s*(store\.(?:search|recent|get)|pulse\.snapshot|ows\.day|events\.recent)\s*:\s*(.*?)>>", re.S)
_ARG_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def parse_tool_calls(content: str) -> list[tuple[str, dict[str, str]]]:
    out: list[tuple[str, dict[str, str]]] = []
    for m in _TOOL_CALL_RE.finditer(str(content or "")):
        args: dict[str, str] = {}
        for am in _ARG_RE.finditer(m.group(2)):
            args[am.group(1)] = am.group(2)
        out.append((m.group(1), args))
    return out


def strip_tool_calls(content: str) -> str:
    return _TOOL_CALL_RE.sub("", str(content or "")).strip()


def truncate_for_tool(text: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    s = str(text or "")
    if len(s) <= max_chars:
        return s
    return s[: max(0, max_chars - len(TRUNC_MARK))] + TRUNC_MARK


def _signal_filter(text: str) -> str:
    s = str(text or "")
    if SIGNAL_RE.search(s):
        return "[r4:execution_authority=NONE proposal_detected]\n" + s
    return s


def _ro_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect("file:" + db_path + "?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(r[1]) for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    except Exception:
        return set()


def _to_int(s: Any, default: int = 0) -> int:
    try:
        return int(str(s).strip())
    except Exception:
        return default


def _to_float(s: Any, default: float = 0.0) -> float:
    try:
        return float(str(s).strip())
    except Exception:
        return default


# --- 格式化 -----------------------------------------------------------

def _ts_s(ts: Any) -> str:
    try:
        if ts in (None, ""):
            return "?"
        sec = float(ts)
        from datetime import datetime
        from zoneinfo import ZoneInfo
        pdt = datetime.fromtimestamp(sec, ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M PDT")
        return "%s (%s)" % (int(sec), pdt)
    except (TypeError, ValueError, OSError):
        return str(ts)


def _format_msg_row(r: sqlite3.Row) -> str:
    keys = r.keys()
    rid = str(r["id"] if "id" in keys else "?")
    role = str(r["role"] if "role" in keys else "?")
    node = str(r["node_id"] if "node_id" in keys else "?")
    content = str(r["content"] if "content" in keys else "")
    head = "id=%s · ts=%s · role=%s · node=%s" % (rid, _ts_s(r["ts"]), role, node)
    return head + "\n" + truncate_for_tool(_signal_filter(content))


# --- 工具实现 ---------------------------------------------------------
# 日记层(events / grid_diary)不对外开放 —— 工具只查 cloud-* 对话原文(messages + 冷库)。

def tool_search(args: dict[str, str], *, db_path: str, cloud_nodes: list[str]) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "store.search: 缺 query"
    limit = max(1, min(_to_int(args.get("limit"), 5), 50))
    since = _to_float(args.get("since"), 0.0)
    like = "%" + query.replace("%", "\\%").replace("_", "\\_") + "%"
    parts: list[str] = ["store.search query=%r limit=%d since=%s" % (query, limit, int(since))]
    conn = _ro_conn(db_path)
    try:
        nodes_ph = ",".join("?" for _ in cloud_nodes)
        q = ("SELECT id, node_id, role, content, ts FROM messages "
             "WHERE node_id IN (%s) AND content LIKE ? ESCAPE '\\' AND ts >= ? ORDER BY ts DESC LIMIT ?" % nodes_ph)
        rows = conn.execute(q, [*cloud_nodes, like, since, limit]).fetchall()
        parts.append("## 对话命中 %d 条" % len(rows))
        for r in rows:
            parts.append(_format_msg_row(r))
        if "node_id" in _safe_table_cols(conn, "messages_archive"):
            q2 = ("SELECT id, node_id, role, content, ts FROM messages_archive "
                  "WHERE node_id IN (%s) AND content LIKE ? ESCAPE '\\' AND ts >= ? ORDER BY ts DESC LIMIT ?" % nodes_ph)
            rows2 = conn.execute(q2, [*cloud_nodes, like, since, limit]).fetchall()
            if rows2:
                parts.append("## 冷库命中 %d 条" % len(rows2))
                for r in rows2:
                    parts.append(_format_msg_row(r))
    except Exception as exc:
        parts.append("store.search 错误: %s" % str(exc)[:200])
    finally:
        conn.close()
    return truncate_for_tool("\n\n".join(parts))


def _pdt_recent_window(args: dict[str, str]) -> tuple[float, float, str]:
    """PDT calendar window. days=N → 含今天在内的 N 个 PDT 日;默认 1 日(今日 00:00 PDT → 现在)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    pt = ZoneInfo("America/Los_Angeles")
    now = datetime.now(pt)
    start_ts = args.get("start_ts")
    end_ts = args.get("end_ts")
    if start_ts or end_ts:
        lo = _to_float(start_ts, 0.0)
        hi = _to_float(end_ts, now.timestamp())
        label = "range PDT unix-override [%s,%s]" % (int(lo), int(hi))
        return lo, hi, label
    n = max(1, int(_to_float(args.get("days"), 1.0)))
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=n - 1)
    lo, hi = start.timestamp(), now.timestamp()
    label = "range PDT %s .. %s (%d calendar day(s))" % (
        start.strftime("%Y-%m-%d %H:%M"), now.strftime("%Y-%m-%d %H:%M"), n)
    return lo, hi, label


def tool_recent(args: dict[str, str], *, db_path: str, cloud_nodes: list[str]) -> str:
    limit = max(1, min(_to_int(args.get("limit"), 20), 100))
    lo, hi, label = _pdt_recent_window(args)
    parts: list[str] = ["store.recent limit=%d %s" % (limit, label)]
    conn = _ro_conn(db_path)
    try:
        nodes_ph = ",".join("?" for _ in cloud_nodes)
        q = ("SELECT id, node_id, role, content, ts FROM messages "
             "WHERE node_id IN (%s) AND ts >= ? AND ts <= ? ORDER BY ts DESC LIMIT ?" % nodes_ph)
        rows = conn.execute(q, [*cloud_nodes, lo, hi, limit]).fetchall()
        parts.append("## 对话 %d 条" % len(rows))
        for r in rows:
            parts.append(_format_msg_row(r))
    except Exception as exc:
        parts.append("store.recent 错误: %s" % str(exc)[:200])
    finally:
        conn.close()
    return truncate_for_tool("\n\n".join(parts))


def tool_get(args: dict[str, str], *, db_path: str, cloud_nodes: list[str]) -> str:
    rid = (args.get("id") or "").strip()
    if not rid:
        return "store.get: 缺 id"
    parts: list[str] = ["store.get id=%s" % rid]
    conn = _ro_conn(db_path)
    try:
        r = conn.execute("SELECT id, node_id, role, content, ts FROM messages WHERE id=?", (rid,)).fetchone()
        if r:
            parts.append("## messages 原文")
            parts.append(_format_msg_row(r))
            return truncate_for_tool("\n\n".join(parts))
        if "id" in _safe_table_cols(conn, "messages_archive"):
            r = conn.execute("SELECT id, node_id, role, content, ts FROM messages_archive WHERE id=?", (rid,)).fetchone()
            if r:
                parts.append("## messages_archive 原文")
                parts.append(_format_msg_row(r))
                return truncate_for_tool("\n\n".join(parts))
        parts.append("未找到 id=%s(日记层不对外开放)" % rid)
    except Exception as exc:
        parts.append("store.get 错误: %s" % str(exc)[:200])
    finally:
        conn.close()
    return truncate_for_tool("\n\n".join(parts))


# --- 第五节三工具:跨项目只读实况(侯) ----------------------------------
# pulse.snapshot()  → alpha 8600 /api/pulse,只取 heat 排序 + 健康灯,剥 raw rows
# ows.day(date)     → OWS 8620 /api/day/{date},gex_unreliable 时文本显式标"参考不可信"
# events.recent(kind, limit) → 8501 events 表,kind 白名单=aether_*+stock_card.v1,日记类硬拒
# 三者均只读、过 SIGNAL_RE、3k 截断、计入每轮 3 次上限。

import urllib.request
import urllib.error

PULSE_BASE = os.getenv("PULSE_BASE", "http://127.0.0.1:8600")
OWS_BASE = os.getenv("OWS_BASE", "http://127.0.0.1:8620")


def _http_get_json(url: str, timeout: float = 6.0) -> tuple[Any, str | None]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, "HTTP %d" % e.code
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:160]


def tool_pulse_snapshot(args: dict[str, str], **_kw) -> str:
    """alpha 热力面快照:heat 排序 + 健康灯,剥 raw equity rows。"""
    data, err = _http_get_json(PULSE_BASE + "/api/pulse")
    parts: list[str] = ["pulse.snapshot"]
    if err:
        parts.append("不可达: %s(8600 alpha 未起或不可达就说不可达)" % err)
        return truncate_for_tool("\n".join(parts))
    wl = data.get("watchlist") or []
    equity = data.get("equity") or []
    sources = data.get("sources") or {}
    meta = data.get("meta") or {}
    ftm = data.get("factorTruthMeta") or {}
    nom = data.get("nomination") or {}
    parts.append("## 健康灯")
    parts.append("age_level=%s · factorTruth=%s · pipeline_delay=%ss" % (
        meta.get("age_level", "?"), ftm.get("status", "?"), meta.get("pipeline_delay_s", "?")))
    parts.append("quote_asof=%s · store_age=%ss" % (meta.get("quote_asof_et", "?"), meta.get("store_age_s", "?")))
    parts.append("## 热力面 nomination cap=%s seats=%s overflow=%s asof=%s" % (
        nom.get("cap", "?"), nom.get("seats_n", "?"), nom.get("overflow_n", "?"), nom.get("asof", "?")))
    parts.append("## watchlist(env 顺序) %s" % ",".join(str(s) for s in wl))
    parts.append("## heat 排序(symbol · env_order · ret_1d · ret_5m · source)")
    for e in equity[:12]:
        f = e.get("factors") or {}
        parts.append("%s · order=%s · ret_1d=%s · ret_5m=%s · src=%s" % (
            e.get("symbol", "?"), e.get("env_order", "?"),
            f.get("ret_1d"), f.get("ret_5m"), sources.get(e.get("symbol"), "?")))
    sc = data.get("scan_candidates") or []
    if sc:
        parts.append("## scan 候选 top5")
        for c in sc[:5]:
            parts.append("%s · score=%s · last_on=%s" % (c.get("symbol"), c.get("score"), c.get("last_on")))
    return truncate_for_tool(_signal_filter("\n".join(parts)))


def tool_ows_day(args: dict[str, str], **_kw) -> str:
    """OWS 单日 GEX/IVP 快照;gex_unreliable 时显式标"参考不可信"。"""
    date = (args.get("date") or "").strip()
    if not date:
        return "ows.day: 缺 date(YYYY-MM-DD)"
    data, err = _http_get_json(OWS_BASE + "/api/day/" + date)
    parts: list[str] = ["ows.day date=%s" % date]
    if err:
        parts.append("等待 Theta 数据 · %s(OWS 8620 无快照或不可达)" % err)
        return truncate_for_tool("\n".join(parts))
    snap = data.get("snap") or {}
    feats = data.get("features") or {}
    gx = data.get("gex") or {}
    gauges = data.get("gauges") or {}
    net = gx.get("net_gex_musd_per_1pct")
    # gex_unreliable 判定:net==0 或 atm_iv30 缺(Theta FREE OI=0 同族)
    gex_unreliable = (net in (0, None, "0")) or (feats.get("atm_iv30") is None)
    parts.append("## 标的 %s spot=%s · %s · src=%s" % (
        snap.get("underlying"), snap.get("spot"), snap.get("ts"), snap.get("source")))
    parts.append("## 特征 ATM_IV30=%s · RV20=%s · IVR=%s · IVP=%s · VRP20=%s · EM30=%s" % (
        feats.get("atm_iv30"), feats.get("rv20"), feats.get("ivr"), feats.get("ivp"),
        feats.get("vrp20"), feats.get("expected_move_30d")))
    parts.append("## NetGEX %sM$/1%% · flip=%s" % (net, gx.get("gamma_flip")))
    if gex_unreliable:
        parts.append("⚠ GEX 参考不可信(net=0 或 IV30 缺 — Theta FREE OI=0 同族;付费档到位后自动复活)")
    parts.append("assumption: %s" % gx.get("assumption"))
    parts.append("## 数据质量 raw=%s clean=%s quar=%s(%.0f%%) stale=%.0f%% · rmse=%s" % (
        gauges.get("rows_raw"), gauges.get("rows_clean"), gauges.get("rows_quarantine"),
        gauges.get("quarantine_pct") or 0, gauges.get("stale_pct") or 0, gauges.get("smile_rmse_worst")))
    return truncate_for_tool(_signal_filter("\n".join(parts)))


def tool_events_recent(args: dict[str, str], *, db_path: str | None = None, **_kw) -> str:
    """8501 events 表最近 N 条;kind 白名单(aether_*+stock_card.v1),日记类硬拒。"""
    try:
        from code_task import event_kinds as K
    except Exception:  # noqa: BLE001
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import event_kinds as K
    kind = (args.get("kind") or "").strip()
    if not kind:
        return "events.recent: 缺 kind(白名单:aether_* / stock_card.v1;grid_diary 硬拒)"
    if K.is_diary_kind(kind):
        return "events.recent: 日记层(kind=%s)不对外开放" % kind
    if not K.is_cloud_tool_allowed(kind):
        return "events.recent: kind=%s 不在白名单(仅 aether_* / stock_card.v1)" % kind
    limit = max(1, min(_to_int(args.get("limit"), 10), 20))
    parts: list[str] = ["events.recent kind=%s limit=%d" % (kind, limit)]
    conn = _ro_conn(db_path or _store_db_path())
    try:
        rows = conn.execute(
            "SELECT id, source, kind, payload, ts FROM events WHERE kind=? ORDER BY id DESC LIMIT ?",
            (kind, limit)).fetchall()
        parts.append("## 命中 %d 条" % len(rows))
        for r in rows:
            try:
                pl = json.loads(r["payload"]) if r["payload"] else {}
            except Exception:  # noqa: BLE001
                pl = {}
            body = json.dumps(pl, ensure_ascii=False)
            parts.append("id=%s · ts=%s · source=%s · %s" % (
                r["id"], _ts_s(r["ts"]), r["source"], truncate_for_tool(_signal_filter(body), 1500)))
    except Exception as exc:  # noqa: BLE001
        parts.append("events.recent 错误: %s" % str(exc)[:200])
    finally:
        conn.close()
    return truncate_for_tool("\n".join(parts))


_TOOL_FUNCS = {
    "store.search": tool_search,
    "store.recent": tool_recent,
    "store.get": tool_get,
    "pulse.snapshot": tool_pulse_snapshot,
    "ows.day": tool_ows_day,
    "events.recent": tool_events_recent,
}


def execute_tool(name: str, args: dict[str, str], *, db_path: str | None = None,
                 cloud_nodes: list[str] | None = None) -> str:
    fn = _TOOL_FUNCS.get(name)
    if fn is None:
        return "未知工具: %s" % name
    return fn(args, db_path=db_path or _store_db_path(),
              cloud_nodes=cloud_nodes or ["cloud-glm52", "cloud", "cloud-kimi"])


def run_tool_round(content: str, *, db_path: str | None = None,
                   cloud_nodes: list[str] | None = None,
                   max_calls: int = MAX_TOOL_CALLS_PER_ROUND) -> tuple[str, list[str]]:
    """解析并执行本轮所有工具调用。返回 (拼接结果块, 已执行 name 列表)。

    超过 max_calls 的调用被忽略并附提示。
    """
    calls = parse_tool_calls(content)
    if not calls:
        return "", []
    results: list[str] = []
    done: list[str] = []
    for i, (name, args) in enumerate(calls):
        if i >= max_calls:
            results.append("<<tool_limit>> 已达每轮上限 %d,后续调用忽略" % max_calls)
            break
        res = execute_tool(name, args, db_path=db_path, cloud_nodes=cloud_nodes)
        done.append(name)
        results.append("<<tool_result for %s>>\n%s\n<<end_tool_result>>" % (name, res))
    return "\n\n".join(results), done
