"""8790 particle chat ↔ 8501 /store/conversations (7-day epoch window)."""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

_DEMO_ROOT = Path(__file__).resolve().parents[2]
_BASE = os.environ.get("GRID_STORE_BASE", "http://127.0.0.1:8501").rstrip("/")
_TOKEN_PATH = _DEMO_ROOT / "grid-sovereign-runtime" / "config" / "grid_store.token"
_STATE_PATH = Path(__file__).resolve().parent.parent / ".field_chat_memory_state.json"

MEMORY_DAYS = int(os.environ.get("FIELD_MEMORY_DAYS", "7"))
EPOCH_DAYS = int(os.environ.get("FIELD_MEMORY_EPOCH_DAYS", str(MEMORY_DAYS)))
ANCHOR_DATE = os.environ.get("FIELD_MEMORY_EPOCH_ANCHOR", "2026-07-16")
NODE_CHAT = os.environ.get("FIELD_CHAT_NODE_ID", "field-particle")
NODE_COMPILE = os.environ.get("FIELD_COMPILE_NODE_ID", "field-compile")
ALL_NODES = (NODE_CHAT, NODE_COMPILE)
CONTEXT_LIMIT = int(os.environ.get("FIELD_CHAT_CONTEXT_LIMIT", "8"))
COMPILE_CONTEXT_LIMIT = int(os.environ.get("FIELD_COMPILE_CONTEXT_LIMIT", "12"))


def node_for_task(task: str) -> str:
    if task in ("compile_json", "handoff_protocol"):
        return NODE_COMPILE
    return NODE_CHAT


def context_limit_for(task: str) -> int:
    return COMPILE_CONTEXT_LIMIT if task in ("compile_json", "handoff_protocol") else CONTEXT_LIMIT


# backward compat
NODE_ID = NODE_CHAT


def _token() -> str:
    env = (os.environ.get("GRID_STORE_TOKEN") or "").strip()
    if env:
        return env
    if _TOKEN_PATH.is_file():
        return _TOKEN_PATH.read_text(encoding="utf-8").strip()
    return ""


def _headers() -> dict[str, str]:
    hdr = {"Content-Type": "application/json"}
    tok = _token()
    if tok:
        hdr["X-Grid-Token"] = tok
    return hdr


def _parse_anchor() -> dt.date:
    try:
        return dt.date.fromisoformat(ANCHOR_DATE[:10])
    except ValueError:
        return dt.date(2026, 7, 16)


def current_epoch_start(*, today: dt.date | None = None) -> dt.date:
    """Fixed-length epochs from anchor (default anchor = 2026-07-16)."""
    today = today or dt.date.today()
    anchor = _parse_anchor()
    if today < anchor:
        return anchor
    idx = (today - anchor).days // max(1, EPOCH_DAYS)
    return anchor + dt.timedelta(days=idx * max(1, EPOCH_DAYS))


def epoch_start_ts(*, today: dt.date | None = None) -> float:
    start = current_epoch_start(today=today)
    return dt.datetime.combine(start, dt.time.min).timestamp()


def memory_status(*, today: dt.date | None = None) -> dict[str, Any]:
    start = current_epoch_start(today=today)
    end = start + dt.timedelta(days=max(1, EPOCH_DAYS))
    return {
        "node_id": NODE_CHAT,
        "nodes": {"chat": NODE_CHAT, "compile": NODE_COMPILE},
        "anchor": _parse_anchor().isoformat(),
        "epoch_days": EPOCH_DAYS,
        "epoch_start": start.isoformat(),
        "epoch_end_exclusive": end.isoformat(),
        "context_limit": CONTEXT_LIMIT,
        "compile_context_limit": COMPILE_CONTEXT_LIMIT,
        "store_base": _BASE,
    }


def _read_purge_state() -> dict[str, Any]:
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_purge_state(data: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def maybe_purge_epoch(*, client: httpx.Client | None = None, node_id: str | None = None) -> dict[str, Any]:
    """Drop store rows older than current epoch start (once per epoch, per node)."""
    epoch = current_epoch_start().isoformat()
    state = _read_purge_state()
    purged_map: dict[str, Any] = dict(state.get("purged_nodes") or {})
    targets = [node_id] if node_id else list(ALL_NODES)
    before_ts = epoch_start_ts()
    own = client is None
    if own:
        client = httpx.Client(timeout=12.0)
    total_deleted = 0
    try:
        for nid in targets:
            if purged_map.get(nid) == epoch:
                continue
            r = client.post(
                f"{_BASE}/store/conversations/{nid}/purge",
                headers=_headers(),
                json={"before_ts": before_ts},
            )
            if r.status_code >= 400:
                return {"purged": False, "epoch_start": epoch, "node_id": nid, "error": r.text[:200]}
            deleted = int(r.json().get("deleted") or 0)
            total_deleted += deleted
            purged_map[nid] = epoch
        _write_purge_state({"last_purged_epoch": epoch, "purged_nodes": purged_map, "purged_at": time.time()})
        return {"purged": total_deleted > 0, "epoch_start": epoch, "deleted": total_deleted, "nodes": targets}
    except Exception as exc:
        return {"purged": False, "epoch_start": epoch, "error": str(exc)[:200]}
    finally:
        if own and client is not None:
            client.close()


def sanitize_gateway_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep only complete user→assistant turns; drop orphan users and bad ordering."""
    pending_user: dict[str, str] | None = None
    out: list[dict[str, str]] = []
    for msg in history:
        role = msg.get("role")
        content = msg.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        if role == "user":
            pending_user = {"role": "user", "content": text}
            continue
        if pending_user is None:
            continue
        out.append(pending_user)
        out.append({"role": "assistant", "content": text})
        pending_user = None
    return out


def strip_trailing_users(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Drop orphan user turns at the tail (failed saves / empty gateway replies)."""
    out = list(history)
    while out and out[-1].get("role") == "user":
        out.pop()
    return out


def fetch_history(*, task: str = "chat", client: httpx.Client | None = None) -> list[dict[str, str]]:
    """Recent user/assistant turns within current epoch for the task lane."""
    node_id = node_for_task(task)
    maybe_purge_epoch(client=client, node_id=node_id)
    since_ts = epoch_start_ts()
    limit = context_limit_for(task)
    own = client is None
    if own:
        client = httpx.Client(timeout=12.0)
    try:
        r = client.get(
            f"{_BASE}/store/conversations/{node_id}",
            params={"limit": 500, "since_ts": since_ts},
            headers=_headers(),
        )
        if r.status_code >= 400:
            return []
        rows = r.json()
        out: list[dict[str, str]] = []
        for row in rows:
            role = row.get("role")
            content = row.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                out.append({"role": role, "content": content})
        return sanitize_gateway_history(out)[-limit:]
    except Exception:
        return []
    finally:
        if own and client is not None:
            client.close()


def fetch_all_lanes(*, client: httpx.Client | None = None) -> dict[str, list[dict[str, str]]]:
    return {
        "chat": fetch_history(task="chat", client=client),
        "compile": fetch_history(task="compile_json", client=client),
    }


def _post_msgs(
    msgs: list[dict[str, Any]],
    *,
    task: str,
    client: httpx.Client | None = None,
) -> bool:
    if not msgs:
        return False
    node_id = node_for_task(task)
    own = client is None
    if own:
        client = httpx.Client(timeout=12.0)
    try:
        r = client.post(
            f"{_BASE}/store/conversations/{node_id}/messages",
            headers=_headers(),
            json=msgs,
        )
        return r.status_code < 400
    except Exception:
        return False
    finally:
        if own and client is not None:
            client.close()


def append_user(
    user: str | None,
    *,
    task: str = "chat",
    client: httpx.Client | None = None,
    surface: str = "8790",
    attachment_note: str | None = None,
) -> bool:
    """调模型前落库用户轮(+[文件])。"""
    msgs: list[dict[str, Any]] = []
    if attachment_note and str(attachment_note).strip():
        msgs.append({
            "role": "system",
            "content": f"[文件] {attachment_note.strip()}",
            "surface": surface,
        })
    if user and user.strip():
        msgs.append({"role": "user", "content": user.strip(), "surface": surface})
    return _post_msgs(msgs, task=task, client=client)


def append_assistant(
    assistant: str | None,
    *,
    task: str = "chat",
    client: httpx.Client | None = None,
    surface: str = "8790",
) -> bool:
    if not assistant or not str(assistant).strip():
        return False
    return _post_msgs(
        [{"role": "assistant", "content": assistant.strip(), "surface": surface}],
        task=task,
        client=client,
    )


def append_turn(
    user: str | None,
    assistant: str | None,
    *,
    task: str = "chat",
    client: httpx.Client | None = None,
    surface: str = "8790",
    attachment_note: str | None = None,
) -> bool:
    """兼容旧调用;新路径应分步 append_user → 模型 → append_assistant。"""
    ok_u = True
    if (user and user.strip()) or (attachment_note and str(attachment_note).strip()):
        ok_u = append_user(
            user, task=task, client=client, surface=surface,
            attachment_note=attachment_note,
        )
    ok_a = True
    if assistant and assistant.strip():
        ok_a = append_assistant(
            assistant, task=task, client=client, surface=surface,
        )
    return bool(ok_u and ok_a)


def _soul_inject_prefix(query: str) -> list[dict[str, Any]]:
    """唯一上下文源:grid_mem inject_messages(read 近程窗 + recall)。"""
    try:
        import sys

        root = _DEMO_ROOT
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from grid_mem import DEFAULT_STORE_DB, inject_messages

        db = os.environ.get("GRID_STORE_DB") or DEFAULT_STORE_DB
        if not db or not os.path.isfile(db):
            return []
        return inject_messages(db, "8790", query or "")
    except Exception:
        return []


def build_gateway_messages(
    body: dict[str, Any],
    msg: str,
    *,
    continue_user: str,
    image: str | None = None,
) -> list[dict[str, Any]]:
    """组装 gateway messages:魂组注入替换原 history,不并存、不拼接 store history。"""
    def user_msg(text: str, img: str | None = None) -> dict[str, Any]:
        if img and str(img).startswith("data:image/"):
            return {
                "role": "user",
                "content": [
                    {"type": "text", "text": text or "分析这张图"},
                    {"type": "image_url", "image_url": {"url": img}},
                ],
            }
        return {"role": "user", "content": text}

    seed = (body.get("original_message") or msg or "").strip()
    prefix = _soul_inject_prefix(seed or msg)
    if body.get("continue") and body.get("prior_text"):
        return [
            *prefix,
            user_msg(seed or msg),
            {"role": "assistant", "content": body["prior_text"]},
            {"role": "user", "content": continue_user},
        ]
    return [*prefix, user_msg(msg, image)]


def memory_user_text(msg: str, *, has_image: bool) -> str:
    text = (msg or "").strip()
    if has_image:
        return (text or "[图]") + " [📷]"
    return text


def uses_memory(task: str) -> bool:
    return task in ("chat", "diary", "compile_json", "handoff_protocol")
