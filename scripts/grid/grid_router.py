#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grid Router v2.0 — :8500 独立路由层(8501 9B 推理节点不承担路由)。

路由结果三态:
  grid_local    → core (8501)
  ollama_coder  → coder (Ollama)
  cc_candidate  → AUTO 仅产出候选,不调用 CC,待 cc_confirmed
  cc_cli        → 显式 CC 车道 + cc_confirmed 后执行 cloud CLI

CC 只收 task-scoped envelope(末条用户消息 + 任务标记),禁止 flatten 全历史。
returncode≠0 / 超时 / 畸形 envelope → 结构化失败(非 HTTP 200 finish stop)。
禁止 session resume 与 force-cloud 斜杠指令。
protected_scopes 配置项阻止 AUTO 外路由。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROUTER_DIR = Path(os.environ.get("ROUTER_DIR", "~/Desktop/GridRouter")).expanduser()
PORT = int(os.environ.get("ROUTER_PORT", "8500"))
RULES_FILE = ROUTER_DIR / "router_rules.json"
ROUTER_TOKEN = os.environ.get("ROUTER_TOKEN", "").strip()
CLI_WHITELIST = {"claude"}

OUTCOME_GRID_LOCAL = "grid_local"
OUTCOME_OLLAMA_CODER = "ollama_coder"
OUTCOME_CC_CANDIDATE = "cc_candidate"
OUTCOME_CC_CLI = "cc_cli"

TARGET_CORE = "core"
TARGET_CODER = "coder"
TARGET_CLOUD = "cloud"

CC_SLASHES = ("/cloud", "/deploy", "/scan")
CC_MODEL_NAMES = frozenset({"cloud", "cc"})
SCAN_CLI_MODEL = os.environ.get("GRID_SCAN_CLI_MODEL", "claude-sonnet-4-6").strip()
CONFIRM_LAST_USER_RE = re.compile(r"^\s*CONFIRM\s*$", re.I)

# 合法确认凭证(三选一,强度在凭证定义里):
#   1. payload.cc_confirmed === true   (UI / 显式程序化)
#   2. payload.confirmed === true      (launchd/run_scan 自动化; 必须 bool)
#   3. 末条 user 恰为 CONFIRM, 且满足锚点之一:
#        - payload.cc_task 非空(AUTO/UI 二次提交)
#        - 上一条 user 以 /cloud|/deploy|/scan 或 @CC 开头(聊天两步确认)
# 删除: /force-cloud, cc_session, 历史消息里的 CONFIRM, confirmed:"true" 字符串

DEFAULT_RULES: dict[str, Any] = {
    "targets": {
        "core": {
            "style": "openai",
            "url": "http://127.0.0.1:8501/v1",
            "model": "demo/aster",
            "key": "",
        },
        "coder": {
            "style": "openai",
            "url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5-coder",
            "key": "",
        },
        "cloud": {
            "style": "cli",
            "cmd": ["claude", "-p", "--output-format", "json"],
            "extra_args": [
                "--model",
                SCAN_CLI_MODEL,
                "--allowedTools",
                "Read",
                "--max-turns",
                "6",
            ],
            "cli_model": SCAN_CLI_MODEL,
            "timeout": 600,
            "model": "claude-code",
        },
    },
    "slash": {
        "/code": "coder",
        "/coder": "coder",
        "/cloud": "cloud",
        "/deploy": "cloud",
        "/scan": "cloud",
        "/core": "core",
    },
    "keywords": {
        "coder": [
            "```",
            "写代码",
            "改代码",
            "写个脚本",
            "重构",
            "报错",
            "traceback",
            "stack trace",
            "debug",
            "单元测试",
        ],
        "cloud": [],
    },
    "protected_scopes": {
        "scopes": [
            "diary",
            "identity",
            "memory_palace",
            "gateway_core",
            "seven_day_memory",
            "field_anchor",
        ],
        "domains": {
            "diary": {
                "aliases": [
                    "日记",
                    "diary",
                    "daily log",
                    "journal entry",
                    "journal",
                    "今晚记",
                    "写信",
                    "回信",
                ],
            },
            "memory_palace": {
                "aliases": [
                    "memory palace",
                    "记忆宫",
                    "记忆宫殿",
                    "palace vault",
                    "vault room",
                ],
            },
            "identity": {
                "aliases": [
                    "who are you",
                    "what are you",
                    "identity anchor",
                    "你是谁",
                    "身份锚",
                ],
            },
        },
        "prompt_patterns": [
            r"\bdiary\b",
            r"日记",
            r"memory.?palace",
            r"who are you",
            r"回信",
        ],
    },
    "default": "core",
}

CODE_HINT = re.compile(
    r"```|\bTraceback\b|\bdef |\bimport |\bfunction |\bconst |\bclass "
    r"|\bnpm |\bpip |\bgit |error:|Exception\b",
    re.I,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_rules() -> dict[str, Any]:
    ROUTER_DIR.mkdir(parents=True, exist_ok=True)
    if not RULES_FILE.exists():
        RULES_FILE.write_text(
            json.dumps(DEFAULT_RULES, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    try:
        rules = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    except Exception:
        rules = dict(DEFAULT_RULES)
    bad: list[tuple[str, str]] = []
    for name, t in list(rules.get("targets", {}).items()):
        if t.get("style") == "cli":
            exe = Path(str((t.get("cmd") or ["?"])[0])).name
            if exe not in CLI_WHITELIST:
                bad.append((name, exe))
                del rules["targets"][name]
    for name, exe in bad:
        print("[rules] 拒绝 cli target %r: %r 不在白名单 %s" % (name, exe, sorted(CLI_WHITELIST)))
    return rules


def log_decision(entry: dict[str, Any]) -> None:
    try:
        f = ROUTER_DIR / ("router_%s.jsonl" % datetime.now().strftime("%Y-%m-%d"))
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def recent_decisions(n: int = 50) -> list[dict[str, Any]]:
    files = sorted(ROUTER_DIR.glob("router_*.jsonl"))
    if not files:
        return []
    lines = files[-1].read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(l) for l in lines[-n:]]


def user_messages(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in msgs if m.get("role") == "user"]


def message_text(msg: dict[str, Any]) -> str:
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def last_user_text(msgs: list[dict[str, Any]]) -> str:
    users = user_messages(msgs)
    if not users:
        return ""
    return message_text(users[-1])


def confirm_chain_active(payload: dict[str, Any]) -> tuple[bool, str]:
    """末条 CONFIRM + 上一条 user 为 CC 斜杠/@CC — 聊天两步确认。"""
    users = user_messages(payload.get("messages") or [])
    if len(users) < 2:
        return False, ""
    last = message_text(users[-1])
    if not CONFIRM_LAST_USER_RE.match(last or ""):
        return False, ""
    prev = message_text(users[-2]).lstrip()
    prev_low = prev.lower()
    if any(prev.startswith(s) for s in CC_SLASHES):
        return True, "message:CONFIRM+slash_chain"
    if prev_low.startswith("@cc") or "@cc" in prev_low:
        return True, "message:CONFIRM+atcc_chain"
    return False, ""


def parse_confirmation(payload: dict[str, Any]) -> tuple[bool, str]:
    """
    返回 (通过, 凭证类型)。
    仅认 bool True; 不认字符串 "true"; 不认历史 CONFIRM。
    """
    if payload.get("cc_confirmed") is True:
        return True, "payload:cc_confirmed"
    if payload.get("confirmed") is True:
        return True, "payload:confirmed"
    chain_ok, chain_kind = confirm_chain_active(payload)
    if chain_ok:
        return True, chain_kind
    task = str(payload.get("cc_task") or "").strip()
    last = last_user_text(payload.get("messages") or [])
    if CONFIRM_LAST_USER_RE.match(last or "") and task:
        return True, "message:CONFIRM+cc_task"
    if CONFIRM_LAST_USER_RE.match(last or ""):
        return False, "reject:bare_CONFIRM"
    if payload.get("cc_confirmed") or payload.get("confirmed"):
        return False, "reject:non_bool_confirm"
    return False, ""


def cc_confirmed(payload: dict[str, Any]) -> bool:
    return parse_confirmation(payload)[0]


def cc_lane_task_text(payload: dict[str, Any]) -> str:
    """CC 执行用的任务正文 — 来自 cc_task 或 CONFIRM 链的上一条 user。"""
    task = str(payload.get("cc_task") or "").strip()
    if task:
        return task
    users = user_messages(payload.get("messages") or [])
    if len(users) >= 2 and CONFIRM_LAST_USER_RE.match(message_text(users[-1]) or ""):
        return strip_cc_prefix(message_text(users[-2]))
    return strip_cc_prefix(last_user_text(payload.get("messages") or []))


def _normalize_protected_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _alias_hits(normalized: str, alias: str) -> bool:
    a = _normalize_protected_text(alias)
    if not a or not normalized:
        return False
    if a in normalized:
        return True
    if re.search(r"^[a-z0-9 .'-]+$", a):
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", normalized))
    return False


def _protected_corpus(payload: dict[str, Any]) -> str:
    """仅末条 user + system — 不用 assistant 历史,防 CONFIRM/对话绕过。"""
    parts: list[str] = []
    msgs = payload.get("messages") or []
    last_u = last_user_text(msgs)
    if last_u:
        parts.append(last_u)
    for msg in msgs:
        if msg.get("role") == "system":
            parts.append(message_text(msg))
    return "\n".join(p for p in parts if p)


def protected_scope(rules: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, str]:
    """
    判定顺序(前层优先,后层不可覆盖前层否定):
      T1 scope/grid_scope 字段 ∈ scopes 名单(store/UI 写入,不依赖措辞)
      T2 payload.protected === true
      T3 domains.*.aliases 归一化别名(防换说法绕过)
      T4 prompt_patterns 正则(legacy)
    """
    cfg = rules.get("protected_scopes") or {}
    scopes = {str(s).strip().lower() for s in (cfg.get("scopes") or []) if str(s).strip()}
    body_scope = str(payload.get("grid_scope") or payload.get("scope") or "").strip().lower()
    if body_scope and body_scope in scopes:
        return True, "scope_field:" + body_scope
    if payload.get("protected") is True:
        return True, "body:protected"

    corpus = _protected_corpus(payload)
    norm = _normalize_protected_text(corpus)
    for domain, spec in (cfg.get("domains") or {}).items():
        for alias in spec.get("aliases") or []:
            if _alias_hits(norm, str(alias)):
                return True, "domain:" + str(domain)

    patterns = [
        re.compile(str(p), re.I)
        for p in (cfg.get("prompt_patterns") or [])
        if str(p).strip()
    ]
    if norm:
        for pat in patterns:
            if pat.search(norm):
                return True, "pattern:" + pat.pattern
    return False, ""


def strip_cc_prefix(text: str) -> str:
    t = text.lstrip()
    low = t.lower()
    for slash in CC_SLASHES:
        if low.startswith(slash):
            return t[len(slash) :].lstrip()
    if low.startswith("@cc"):
        return t[3:].lstrip(" :，,").strip()
    return t.strip()


def task_scoped_envelope(payload: dict[str, Any]) -> str:
    """CC 只收任务锚定正文 + 可选 [task:…] — 禁止 flatten 全历史。"""
    task = str(payload.get("task") or payload.get("grid_task") or "").strip()
    text = cc_lane_task_text(payload)
    if not text:
        return f"[task:{task}]".strip() if task else ""
    if task:
        return ("[task:%s]\n%s" % (task, text)).strip()
    return text


def strip_slash_from_payload(payload: dict[str, Any], cmd: str) -> dict[str, Any]:
    msgs = payload.get("messages") or []
    new_msgs: list[dict[str, Any]] = []
    done = False
    for msg in msgs:
        if done or msg.get("role") != "user":
            new_msgs.append(msg)
            continue
        c = msg.get("content")
        if isinstance(c, str) and c.lstrip().startswith(cmd):
            msg = dict(msg)
            msg["content"] = c.lstrip()[len(cmd) :].lstrip()
            done = True
        elif isinstance(c, list):
            for i, part in enumerate(c):
                if (
                    isinstance(part, dict)
                    and part.get("type") == "text"
                    and str(part.get("text", "")).lstrip().startswith(cmd)
                ):
                    c2 = [dict(p) if isinstance(p, dict) else p for p in c]
                    c2[i]["text"] = str(c2[i]["text"]).lstrip()[len(cmd) :].lstrip()
                    msg = dict(msg)
                    msg["content"] = c2
                    done = True
                    break
        new_msgs.append(msg)
    p2 = dict(payload)
    p2["messages"] = new_msgs
    return p2


def explicit_cc_lane(
    rules: dict[str, Any],
    payload: dict[str, Any],
    headers: dict[str, str],
) -> tuple[bool, str, dict[str, Any]]:
    targets = rules.get("targets") or {}
    msgs = payload.get("messages") or []
    text = last_user_text(msgs)

    m = str(payload.get("model") or "").strip().lower()
    if m in CC_MODEL_NAMES and TARGET_CLOUD in targets:
        return True, "model:" + m, payload
    cloud_model = str((targets.get(TARGET_CLOUD) or {}).get("model") or "").strip().lower()
    if m and cloud_model and m == cloud_model and TARGET_CLOUD in targets:
        return True, "model:" + m, payload

    xr = str(headers.get("X-Route") or headers.get("x-route") or "").strip()
    if xr == TARGET_CLOUD and TARGET_CLOUD in targets:
        return True, "header:cloud", payload

    stripped = text.lstrip()
    for cmd in CC_SLASHES:
        if stripped.startswith(cmd) and TARGET_CLOUD in targets:
            p2 = strip_slash_from_payload(payload, cmd)
            return True, "slash:" + cmd, p2

    if "@cc" in text.lower():
        return True, "at:cc", payload

    chain_ok, chain_reason = confirm_chain_active(payload)
    if chain_ok:
        return True, chain_reason, payload

    return False, "", payload


def auto_cc_candidate_heuristic(rules: dict[str, Any], text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    for w in rules.get("keywords", {}).get("cloud") or []:
        if str(w).lower() in low:
            return True
    if "```" in text or "Traceback" in text:
        return False
    return len(text) > 500


def outcome_for_target(target_key: str) -> str:
    if target_key == TARGET_CORE:
        return OUTCOME_GRID_LOCAL
    if target_key == TARGET_CODER:
        return OUTCOME_OLLAMA_CODER
    if target_key == TARGET_CLOUD:
        return OUTCOME_CC_CLI
    return OUTCOME_GRID_LOCAL


def decide(
    rules: dict[str, Any],
    payload: dict[str, Any],
    headers: dict[str, str],
) -> tuple[str, str | None, str, dict[str, Any]]:
    """
    返回 (route_outcome, target_key, reason, payload)。
    target_key 为 None 表示 cc_candidate,不转发 upstream。
    """
    targets = rules.get("targets") or {}
    msgs = payload.get("messages") or []
    text = last_user_text(msgs)

    blocked, block_reason = protected_scope(rules, payload)
    if blocked:
        return OUTCOME_GRID_LOCAL, TARGET_CORE, "protected:" + block_reason, payload

    confirm_ok, confirm_kind = parse_confirmation(payload)
    if confirm_ok and str(payload.get("cc_task") or "").strip():
        return OUTCOME_CC_CLI, TARGET_CLOUD, "confirm:" + confirm_kind, payload

    cc_lane, cc_reason, payload = explicit_cc_lane(rules, payload, headers)
    if cc_lane:
        if confirm_ok:
            return OUTCOME_CC_CLI, TARGET_CLOUD, cc_reason + "+" + confirm_kind, payload
        return OUTCOME_CC_CANDIDATE, None, cc_reason, payload

    m = str(payload.get("model") or "").strip()
    if m in targets:
        tk = m
        return outcome_for_target(tk), tk, "model:" + m, payload
    for name, t in targets.items():
        if m and m == t.get("model"):
            return outcome_for_target(name), name, "model:" + m, payload

    xr = str(headers.get("X-Route") or headers.get("x-route") or "").strip()
    if xr in targets:
        if xr == TARGET_CLOUD:
            if confirm_ok:
                return OUTCOME_CC_CLI, TARGET_CLOUD, "header:cloud+" + confirm_kind, payload
            return OUTCOME_CC_CANDIDATE, None, "header:cloud", payload
        return outcome_for_target(xr), xr, "header:" + xr, payload

    stripped = text.lstrip()
    for cmd, tgt in (rules.get("slash") or {}).items():
        if cmd in CC_SLASHES:
            continue
        if stripped.startswith(cmd) and tgt in targets:
            p2 = strip_slash_from_payload(payload, cmd)
            return outcome_for_target(tgt), tgt, "slash:" + cmd, p2

    low = text.lower()
    for tgt, words in (rules.get("keywords") or {}).items():
        if tgt not in targets or tgt == TARGET_CLOUD:
            continue
        for w in words:
            if str(w).lower() in low:
                return outcome_for_target(tgt), tgt, "kw:" + w, payload

    if TARGET_CODER in targets:
        hits = CODE_HINT.findall(text)
        if "```" in text or len(hits) >= 2 or (hits and len(text) > 200):
            return OUTCOME_OLLAMA_CODER, TARGET_CODER, "heuristic:code", payload

    if auto_cc_candidate_heuristic(rules, text) and TARGET_CLOUD in targets:
        return OUTCOME_CC_CANDIDATE, None, "auto:complexity", payload

    d = rules.get("default", TARGET_CORE)
    return outcome_for_target(d), d, "default", payload


def cli_failure_body(
    *,
    route: str,
    error: str,
    exit_code: int | None = None,
    stderr: str = "",
    finish_reason: str = "cc_cli_error",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "error": {"type": "cc_cli", "reason": error},
        "route": route,
        "route_outcome": OUTCOME_CC_CLI,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": ""},
            }
        ],
        "grid_meta": {
            "route_outcome": OUTCOME_CC_CLI,
            "finish_reason": finish_reason,
            "error": error,
        },
    }
    if exit_code is not None:
        body["grid_meta"]["exit_code"] = exit_code
    if stderr:
        body["grid_meta"]["stderr"] = stderr[-500:]
    return body


def cc_candidate_body(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    model = str(payload.get("model") or "grid-router")
    task_hint = cc_lane_task_text(payload) or last_user_text(payload.get("messages") or [])
    return {
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "cc_candidate",
                "message": {
                    "role": "assistant",
                    "content": "",
                },
            }
        ],
        "grid_meta": {
            "route_outcome": OUTCOME_CC_CANDIDATE,
            "awaiting_confirmation": True,
            "reason": reason,
            "cc_task_hint": task_hint[:500] if task_hint else "",
            "confirm_credentials": {
                "payload_cc_confirmed": {
                    "cc_confirmed": True,
                    "cc_task": task_hint,
                    "note": "UI/AUTO 二次 POST — cc_task 必填",
                },
                "payload_confirmed_automation": {
                    "confirmed": True,
                    "note": "仅 run_scan/launchd; bool true",
                },
                "message_confirm_chain": {
                    "messages": [
                        {"role": "user", "content": "/cloud <task>"},
                        {"role": "user", "content": "CONFIRM"},
                    ],
                    "note": "末条必须恰为 CONFIRM; 上一条 user 为 CC 斜杠",
                },
            },
        },
    }


# ---------------------------------------------------------------- forwarding

def _open(req: urllib.request.Request, timeout: float = 600):
    return urllib.request.urlopen(req, timeout=timeout)


def _chunk_out(h: BaseHTTPRequestHandler, data: bytes) -> None:
    h.wfile.write(("%X\r\n" % len(data)).encode("ascii") + data + b"\r\n")


def _chunk_end(h: BaseHTTPRequestHandler) -> None:
    h.wfile.write(b"0\r\n\r\n")


def forward_cli(h: Handler, tgt: dict[str, Any], payload: dict[str, Any], route: str) -> None:
    """cloud = Claude Code CLI — task-scoped envelope only; failures never HTTP 200."""
    extra = list(tgt.get("extra_args") or [])
    cli_model = str(tgt.get("cli_model") or SCAN_CLI_MODEL).strip()
    if "--model" not in extra:
        extra = ["--model", cli_model] + extra
    cmd = list(tgt.get("cmd") or ["claude", "-p", "--output-format", "json"]) + extra
    prompt = task_scoped_envelope(payload)
    if not prompt.strip():
        return h._send(
            502,
            cli_failure_body(route=route, error="empty_task_envelope"),
        )

    try:
        proc = subprocess.run(
            cmd,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=int(tgt.get("timeout", 600)),
        )
    except FileNotFoundError:
        return h._send(
            503,
            cli_failure_body(route=route, error="claude_missing:%s" % cmd[0]),
        )
    except subprocess.TimeoutExpired:
        return h._send(
            504,
            cli_failure_body(route=route, error="timeout"),
        )

    stderr = (proc.stderr or b"").decode("utf-8", "replace")
    out = (proc.stdout or b"").decode("utf-8", "replace").strip()

    if proc.returncode != 0:
        # CC 常把业务错误写在 stdout JSON(result / is_error),勿只报 exit_N
        detail = "exit_%d" % proc.returncode
        try:
            env = json.loads(out) if out else None
            if isinstance(env, dict):
                msg = str(env.get("result") or env.get("error") or "").strip()
                if msg:
                    detail = msg[:240]
                elif env.get("is_error"):
                    detail = "cc_is_error:exit_%d" % proc.returncode
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        if "not logged in" in detail.lower() or "/login" in detail.lower():
            detail = "cc_not_logged_in: 请在本机终端执行 claude 登录(/login)后重试 · " + detail
        return h._send(
            502,
            cli_failure_body(
                route=route,
                error=detail,
                exit_code=proc.returncode,
                stderr=stderr or out[-500:],
            ),
        )

    text = ""
    envelope: dict[str, Any] | None = None
    try:
        envelope = json.loads(out)
        if not isinstance(envelope, dict):
            raise ValueError("not_object")
        text = str(
            envelope.get("result") or envelope.get("text") or envelope.get("content") or ""
        ).strip()
        if not text:
            return h._send(
                502,
                cli_failure_body(route=route, error="empty_result"),
            )
    except (json.JSONDecodeError, ValueError):
        if not out:
            return h._send(
                502,
                cli_failure_body(route=route, error="bad_envelope"),
            )
        text = out

    cli_audit: dict[str, Any] = {"route_outcome": OUTCOME_CC_CLI}
    if isinstance(envelope, dict):
        if envelope.get("total_cost_usd") is not None:
            cli_audit["cost_usd"] = envelope.get("total_cost_usd")
        if envelope.get("duration_ms") is not None:
            cli_audit["duration_ms"] = envelope.get("duration_ms")
        models = list((envelope.get("modelUsage") or {}).keys())
        if models:
            cli_audit["resolved_models"] = models

    if payload.get("stream"):
        if not h._claim():
            return
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("X-Grid-Route", route)
        h.send_header("X-Grid-Route-Outcome", OUTCOME_CC_CLI)
        h.send_header("Transfer-Encoding", "chunked")
        h.end_headers()
        for obj in (
            {
                "object": "chat.completion.chunk",
                "model": tgt["model"],
                "choices": [{"index": 0, "finish_reason": None, "delta": {"content": text}}],
            },
            {
                "object": "chat.completion.chunk",
                "model": tgt["model"],
                "choices": [{"index": 0, "finish_reason": "stop", "delta": {}}],
            },
        ):
            _chunk_out(h, b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n\n")
        _chunk_out(h, b"data: [DONE]\n\n")
        _chunk_end(h)
        return

    resp = {
        "id": "cc",
        "object": "chat.completion",
        "model": tgt["model"],
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }
        ],
        "grid_meta": cli_audit,
    }
    blob = json.dumps(resp, ensure_ascii=False).encode("utf-8")
    if not h._claim():
        return
    h.send_response(200)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("X-Grid-Route", route)
    h.send_header("X-Grid-Route-Outcome", OUTCOME_CC_CLI)
    h.send_header("Content-Length", str(len(blob)))
    h.end_headers()
    h.wfile.write(blob)


def forward_openai(h: Handler, tgt: dict[str, Any], payload: dict[str, Any], route: str, outcome: str) -> None:
    payload = dict(payload)
    payload["model"] = tgt["model"]
    req = urllib.request.Request(
        tgt["url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    if tgt.get("key"):
        req.add_header("Authorization", "Bearer " + tgt["key"])
    resp = _open(req)
    if not h._claim():
        return
    h.send_response(resp.status)
    h.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
    h.send_header("X-Grid-Route", route)
    h.send_header("X-Grid-Route-Outcome", outcome)
    h.send_header("Transfer-Encoding", "chunked")
    h.end_headers()
    while True:
        chunk = resp.read(4096)
        if not chunk:
            break
        _chunk_out(h, chunk)
    _chunk_end(h)


def forward_anthropic(h: Handler, tgt: dict[str, Any], payload: dict[str, Any], route: str, outcome: str) -> None:
    msgs = payload.get("messages") or []
    system = "\n".join(
        m["content"]
        for m in msgs
        if m.get("role") == "system" and isinstance(m.get("content"), str)
    )
    conv = [{"role": m["role"], "content": m["content"]} for m in msgs if m.get("role") in ("user", "assistant")]
    body = {
        "model": tgt["model"],
        "max_tokens": int(payload.get("max_tokens") or 4096),
        "messages": conv,
    }
    if system:
        body["system"] = system
    stream = bool(payload.get("stream"))
    if stream:
        body["stream"] = True
    req = urllib.request.Request(
        tgt["url"].rstrip("/") + "/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": tgt.get("key", ""),
            "anthropic-version": "2023-06-01",
        },
    )
    resp = _open(req)

    if not stream:
        data = json.loads(resp.read().decode("utf-8"))
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        u = data.get("usage", {})
        out = {
            "id": data.get("id", "msg"),
            "object": "chat.completion",
            "model": tgt["model"],
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": text},
                }
            ],
            "usage": {
                "prompt_tokens": u.get("input_tokens", 0),
                "completion_tokens": u.get("output_tokens", 0),
            },
            "grid_meta": {"route_outcome": outcome},
        }
        blob = json.dumps(out, ensure_ascii=False).encode("utf-8")
        if not h._claim():
            return
        h.send_response(200)
        h.send_header("Content-Type", "application/json; charset=utf-8")
        h.send_header("X-Grid-Route", route)
        h.send_header("X-Grid-Route-Outcome", outcome)
        h.send_header("Content-Length", str(len(blob)))
        h.end_headers()
        h.wfile.write(blob)
        return

    if not h._claim():
        return
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream")
    h.send_header("X-Grid-Route", route)
    h.send_header("X-Grid-Route-Outcome", outcome)
    h.send_header("Transfer-Encoding", "chunked")
    h.end_headers()

    def emit(obj: dict[str, Any]) -> None:
        _chunk_out(h, b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n\n")

    buf = b""
    while True:
        chunk = resp.read(1024)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            try:
                ev = json.loads(line[5:].strip().decode("utf-8"))
            except Exception:
                continue
            t = ev.get("type")
            if t == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                emit(
                    {
                        "object": "chat.completion.chunk",
                        "model": tgt["model"],
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": None,
                                "delta": {"content": ev["delta"]["text"]},
                            }
                        ],
                    }
                )
            elif t == "message_stop":
                emit(
                    {
                        "object": "chat.completion.chunk",
                        "model": tgt["model"],
                        "choices": [{"index": 0, "finish_reason": "stop", "delta": {}}],
                    }
                )
    _chunk_out(h, b"data: [DONE]\n\n")
    _chunk_end(h)


# ---------------------------------------------------------------- HTTP layer

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "GridRouter/2.0"

    def _claim(self) -> bool:
        if getattr(self, "_responded", False):
            return False
        self._responded = True
        return True

    def _send(self, code: int, body: dict[str, Any] | list[Any] | str, ctype: str = "application/json; charset=utf-8") -> None:
        if not self._claim():
            return
        if isinstance(body, (dict, list)):
            blob = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            blob = body.encode("utf-8")
        else:
            blob = bytes(body)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def log_message(self, fmt: str, *args: object) -> None:
        print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

    def do_GET(self) -> None:
        self._responded = False
        p = urllib.parse.urlparse(self.path).path
        rules = load_rules()
        if p in ("/routes", "/health") and ROUTER_TOKEN:
            if self.headers.get("X-Router-Token", "") != ROUTER_TOKEN:
                return self._send(403, {"error": "bad or missing X-Router-Token"})
        if p == "/routes":
            return self._send(200, recent_decisions())
        if p == "/health":
            out: dict[str, Any] = {"version": "2.0"}
            for name, t in rules["targets"].items():
                if t["style"] == "cli":
                    exe = (t.get("cmd") or ["claude"])[0]
                    out[name] = ("cli:" + shutil.which(exe)) if shutil.which(exe) else "cli 未找到: " + exe
                    continue
                if t["style"] == "anthropic":
                    out[name] = "configured" if t.get("key") else "no-key"
                    continue
                try:
                    _open(urllib.request.Request(t["url"].rstrip("/") + "/models"), timeout=3)
                    out[name] = "up"
                except Exception as e:
                    out[name] = "down: %s" % e
            return self._send(200, out)
        if p == "/v1/models":
            data = [
                {
                    "id": name,
                    "object": "model",
                    "owned_by": t["style"],
                    "routed_model": t["model"],
                }
                for name, t in rules["targets"].items()
            ]
            return self._send(200, {"object": "list", "data": data})
        return self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        self._responded = False
        p = urllib.parse.urlparse(self.path).path
        if p not in ("/v1/chat/completions", "/chat/completions"):
            return self._send(404, {"error": "not found"})
        rules = load_rules()
        try:
            n = int(self.headers.get("Content-Length", "0") or "0")
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as e:
            return self._send(400, {"error": "bad json: %s" % e})

        hdrs = {k: v for k, v in self.headers.items()}
        outcome, target_key, reason, payload = decide(rules, payload, hdrs)

        log_decision(
            {
                "ts": utcnow(),
                "route_outcome": outcome,
                "target": target_key,
                "reason": reason,
                "model": (rules["targets"].get(target_key or "") or {}).get("model"),
                "chars": len(last_user_text(payload.get("messages") or [])),
            }
        )

        if outcome == OUTCOME_CC_CANDIDATE:
            body = cc_candidate_body(payload, reason)
            if not self._claim():
                return
            blob = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("X-Grid-Route-Outcome", OUTCOME_CC_CANDIDATE)
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
            return

        if target_key is None:
            return self._send(500, {"error": "missing target for outcome %s" % outcome})

        tgt = rules["targets"].get(target_key)
        if tgt is None:
            return self._send(500, {"error": "unknown target %s" % target_key})
        if tgt["style"] == "anthropic" and not tgt.get("key"):
            return self._send(503, {"error": "anthropic 目标未配置 key(router_rules.json)"})

        try:
            if tgt["style"] == "cli":
                forward_cli(self, tgt, payload, target_key)
            elif tgt["style"] == "anthropic":
                forward_anthropic(self, tgt, payload, target_key, outcome)
            else:
                forward_openai(self, tgt, payload, target_key, outcome)
        except urllib.error.HTTPError as e:
            body = e.read()
            if not self._claim():
                return
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:  # noqa: BLE001
            try:
                self._send(502, {"error": "upstream: %s" % e, "route": target_key, "route_outcome": outcome})
            except Exception:
                pass


def main() -> None:
    rules = load_rules()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Grid Router v2.0 :%d → 规则 %s" % (PORT, RULES_FILE))
    for name, t in rules["targets"].items():
        where = t.get("url") or " ".join(t.get("cmd", ["?"]))
        print("  %-6s %-9s %s (%s)" % (name, t["style"], where, t["model"]))
    print("UI base_url → :%d; 观察面 GET /routes /health" % PORT)
    srv.serve_forever()


if __name__ == "__main__":
    main()
