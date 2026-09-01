"""
Grid Sovereign Gateway V4.1

Merged: Fable 5 local_gateway V3.1 + GPT 5.5 cleanroom gate integration.

Pipeline: pre_filter -> signal score -> concurrency gate -> Ollama (Qwen) -> cleanroom gate -> response

Two layers in one process:
  - Gateway: routes, gates concurrency, formats output
  - Cleanroom: blocks model impersonation, enforces GRID_ABSENT / MODEL_READ

One process, one port, no cloud, no API keys.

Run:  python3 gateway/local_gateway.py
Deps: fastapi, uvicorn, pydantic, httpx
"""

import asyncio
import json
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------- paths

GATEWAY_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = GATEWAY_DIR.parent
DEMO_ROOT = PROJECT_ROOT.parent
SUBSTRATE_SCRIPTS = DEMO_ROOT / "scripts" / "substrate_airlock" / "scripts"
SUBSTRATE_AIRLOCK = DEMO_ROOT / "scripts" / "substrate_airlock"
if str(SUBSTRATE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SUBSTRATE_SCRIPTS))
if str(SUBSTRATE_AIRLOCK) not in sys.path:
    sys.path.insert(0, str(SUBSTRATE_AIRLOCK))
if str(DEMO_ROOT) not in sys.path:
    sys.path.insert(0, str(DEMO_ROOT))
from airlock_bridge import process_lm_studio_body  # noqa: E402
from substrate_gate import gate_clean_content  # noqa: E402
from substrate_sanitizer import sanitize_response  # noqa: E402

from compile_verdict import compute_compile_verdict  # noqa: E402
from chat_stream_integrity import StreamIntegrityTracker, sha256_text  # noqa: E402
from chat_finish import (  # noqa: E402
    build_finish_audit,
    normalize_finish_reason,
    should_continue_chat,
)
from chat_history_clean import clean_chat_messages, had_stale_envelopes  # noqa: E402
from contract_gate import (  # noqa: E402
    UNSAFE_DEBUG_ROUTE_CLASS,
    apply_contract_gate,
)
from contract_lint import apply_contract_lint  # noqa: E402
from gateway_envelope import (  # noqa: E402
    SERVED_BY,
    build_gateway_envelope,
    link_fingerprint,
    set_gateway_started_at,
)
import gateway_envelope  # noqa: E402
from aster_identity import (  # noqa: E402
    ensure_aster_system_message,
    is_aster_model,
    is_vision_model,
    load_aster_chat_system_prompt,
    substrate_model_id,
)
from field_now_context import append_field_now_observer_context  # noqa: E402
from vl_normalize import gate_multimodal, image_blocks  # noqa: E402
from substrate_telemetry import record_request, snapshot as telemetry_snapshot  # noqa: E402
from substrate_backend import (  # noqa: E402
    ollama_chat_payload,
    resolve_substrate_target,
)
from code_task.gateway_execute import build_code_task_request, execute_manual_backend, cc_cli_failure_proof, success_proof
from code_task.backends.glm52_cloud import execute_candidate, shadow_candidate_response
from code_task.manual_backend import cc_cli_allowed, parse_candidate_backend_id, parse_manual_backend_id, substrate_route_class
from code_task import CodeTaskRequest, execute_ollama  # noqa: E402
from token_budget import (  # noqa: E402
    merge_aster_budget,
    openai_thinking_payload,
    resolve_chat_route,
    resolve_max_tokens as budget_resolve_max_tokens,
    thinking_cap,
)
from temperature_policy import resolve_substrate_temperature  # noqa: E402
from expanded_orchestrator import run_expanded_orchestration  # noqa: E402
from expanded_memory import load_store_messages  # noqa: E402
from factory_task_router import (  # noqa: E402
    FACTORY_MEMORY_NODE,
    build_factory_task,
    map_factory_route,
    parse_factory_result,
)
from code_task.cloud_gateway_route import (  # noqa: E402
    cloud_model_catalog,
    match_cloud_model,
    openai_cloud_chat_completion,
    task_cloud_chat_handler,
)

QUARANTINE_DIR = PROJECT_ROOT / "traces" / "quarantine"
NO_THINK_PREFIX = (
    "/no_think\n"
    "Do not output reasoning.\n"
    "Do not output <think>.\n"
    "Do not output reasoning_content.\n"
    "Return final answer only.\n"
    "If reasoning occurs internally, do not expose it.\n"
)
SUBSTRATE_NULL_TEXT = (
    "GRID_ABSENT\n"
    "NO LIVE GRID SIGNAL\n"
    "MODEL CAN ONLY PROVIDE INTERPRETATION AFTER A SIGNED TRACE EXISTS"
)
CLEANROOM_SCRIPT = PROJECT_ROOT / "scripts" / "cleanroom.py"
CLEANROOM_STATE = PROJECT_ROOT / ".grid_cleanroom" / "state.json"
POLICY_PATH = PROJECT_ROOT / "policy" / "cleanroom_policy.json"
CONFIG_PATH = PROJECT_ROOT / "configs" / "gateway_config.json"

# ---------------------------------------------------------------- config
# V4.1 fix#1: config is now loaded from configs/gateway_config.json (was hardcoded
# and the JSON file was dead — editing it did nothing). Defaults below are the
# fallback ONLY when the JSON is missing. Single source of truth = the JSON.

DEFAULT_CONFIG = {
    # V4.2: backend switch. "ollama" -> Ollama /api/chat; "openai" -> any
    # OpenAI-compatible local server (LM Studio, llama.cpp server, vLLM).
    # LOCAL ONLY either way — this is format compat, not cloud.
    "backend": "openai",
    "openai_endpoint": "http://localhost:1234/v1",   # LM Studio default
    "openai_model": "qwen3.5-9b",                     # LM Studio model identifier
    "ollama_endpoint": "http://localhost:11434/api/chat",
    "ollama_model": "qwen3.5:9b",           # V4.1 fix#2: qwen2.5:4b did not exist as a tag
    "ollama_coder_model": "qwen2.5-coder:7b",
    "kimi_k25_cloud_model": "kimi-k2.6:cloud",
    "kimi_k25_cloud_endpoint": "http://localhost:11434/api/chat",
    "glm52_cloud_model": "glm-5.2:cloud",
    "glm52_cloud_endpoint": "http://localhost:11434/api/chat",
    "deepseek_v4_cloud_model": "deepseek-v4-pro:cloud",
    "deepseek_v4_cloud_endpoint": "http://localhost:11434/api/chat",
    "coder_routing_enabled": False,
    "coder_routes": ["compile", "task"],
    "coherence_threshold": 0.87,            # >= this -> deep model hint
    "beacon_phrase": "return to node",
    "max_concurrent": 1,
    "max_queue": 2,
    "cleanroom_enabled": True,
    "bind_host": "127.0.0.1",
    "bind_port": 8501,
    "stream_incremental_gate": True,        # V4.1 fix#4
    # Route token budgets — see config/aster.toml [budget] + gateway_config.json
    "compile_max_tokens": 256,
    "chat_max_tokens": 400,
    "gateway_max_tokens": 1024,
    "task_max_tokens": 4096,
    "thinking_cap": 128,
    "max_reasoning_tokens": 128,
}


def active_model() -> str:
    return CONFIG["openai_model"] if CONFIG["backend"] == "openai" else CONFIG["ollama_model"]


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            file_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            file_cfg.pop("note", None)
            cfg.update({k: v for k, v in file_cfg.items() if v is not None})
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: could not read {CONFIG_PATH}: {e}; using defaults")
    # db_path is derived, not user-config
    cfg["db_path"] = str(GATEWAY_DIR / "gateway_log.db")
    return cfg


CONFIG = merge_aster_budget(load_config(), DEMO_ROOT)
ASTER_CHAT_PROMPT = load_aster_chat_system_prompt(DEMO_ROOT)
ASTER_VIRTUAL_MODEL = "demo/aster"
set_gateway_started_at(time.time())


def response_model_id(request_model: str | None) -> str:
    if is_vision_model(request_model):
        return str(request_model).strip()
    return ASTER_VIRTUAL_MODEL if is_aster_model(request_model) else active_model()


def _vision_request(messages: list, request_model: str | None) -> bool:
    if is_vision_model(request_model):
        return True
    return bool(image_blocks(messages))


def _resolve_upstream_model(messages: list, request_model: str | None) -> str:
    if _vision_request(messages, request_model):
        return str(CONFIG.get("vl_model") or "qwen2.5-vl-3b-instruct")
    return substrate_model_id(request_model, CONFIG["openai_model"])


def resolve_max_tokens(route: str, client_max: int | None = None) -> int:
    return budget_resolve_max_tokens(route, client_max, CONFIG)


def _substrate_usage_from_body(body: dict) -> dict:
    """Extract upstream finish_reason and reasoning vs content token split."""
    choice = (body.get("choices") or [{}])[0]
    usage = body.get("usage") or {}
    det = usage.get("completion_tokens_details") or {}
    reasoning = int(det.get("reasoning_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    finish = str(choice.get("finish_reason") or "unknown")
    return {
        "finish_reason": finish,
        "truncated": finish == "length",
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "content_tokens": max(0, completion - reasoning),
    }


@dataclass
class SubstrateAirlockResult:
    clean_content: str
    gate: dict
    quarantine: dict
    pass_to_aster: bool
    proof: dict
    proof_path: str | None = None
    finish_reason: str = "unknown"
    usage: dict | None = None


def _substrate_extra(sub: SubstrateAirlockResult) -> dict:
    usage = sub.usage or {}
    fr = sub.finish_reason or usage.get("finish_reason") or "unknown"
    return {
        "upstream_finish_reason": fr,
        "truncated": bool(usage.get("truncated") or fr == "length"),
        "substrate_usage": sub.usage,
    }

# ------------------------------------------------- forbidden output patterns
# Loaded from policy or hardcoded fallback. These catch model impersonation.

from impersonation_hits import FORBIDDEN_PATTERNS, _COMPILED, first_impersonation_hit, load_forbidden_patterns  # noqa: E402

def cleanroom_gate_check(text: str) -> dict:
    """
    Inline impersonation check. Does NOT shell out to cleanroom.py for every
    request (too slow for streaming). Instead, runs the same regex patterns
    from policy directly. The full cleanroom.py is for trace signing/verification.
    """
    if not CONFIG["cleanroom_enabled"]:
        return {"blocked": False, "text": text}

    hits = []
    for rx in _COMPILED:
        if rx.search(text):
            hits.append(rx.pattern)

    if hits:
        return {
            "blocked": True,
            "reason": "BLOCK SHELL_NOISE: model attempted impersonation",
            "patterns_matched": hits,
            "original_suppressed": True,
            "text": "GRID_ABSENT\nNO LIVE GRID SIGNAL\nMODEL OUTPUT BLOCKED: impersonation pattern detected.",
        }
    return {"blocked": False, "text": text}


def cleanroom_verify_trace(trace_path: str) -> dict:
    """
    Shell out to cleanroom.py for trace verification.
    Only called when explicitly working with signed traces, not on every request.
    """
    if not CLEANROOM_SCRIPT.exists():
        return {"verified": False, "error": "cleanroom.py not found"}
    result = subprocess.run(
        ["python3", str(CLEANROOM_SCRIPT), "verify", "--trace", trace_path],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    return {
        "verified": result.returncode == 0,
        "output": result.stdout.strip(),
        "error": result.stderr.strip() if result.returncode != 0 else None,
    }


def cleanroom_state() -> dict:
    """Read current cleanroom state without shelling out."""
    if CLEANROOM_STATE.exists():
        return json.loads(CLEANROOM_STATE.read_text(encoding="utf-8"))
    return {"mode": "UNINITIALIZED"}

# ------------------------------------------------- concurrency gate

SEM = asyncio.Semaphore(CONFIG["max_concurrent"])
_waiting = 0
_STREAM_DIAG: dict[str, dict] = {}


class GateBusy(Exception):
    pass


async def acquire_gate():
    global _waiting
    if _waiting >= CONFIG["max_queue"]:
        raise GateBusy()
    _waiting += 1
    try:
        await SEM.acquire()
    finally:
        _waiting -= 1


def release_gate():
    SEM.release()


def busy_429() -> HTTPException:
    return HTTPException(status_code=429, detail={
        "error": "gateway_busy",
        "message": "inference slot and queue are full; retry shortly",
        "running": CONFIG["max_concurrent"], "queue": CONFIG["max_queue"],
    })

# ------------------------------------------------------- signal scoring

HIGH_SIGNAL_TERMS = [
    "return to node", "coherence", "frequency", "signal",
    "router", "gateway", "anchor", "sovereign", "watermark",
    "container", "shell", "interface", "field", "protocol",
]

IMPLEMENTATION_TERMS = ["fastapi", "docker", "python", "json", "toml", "gateway"]

IDENTITY_PROBES = ["who are you", "what are you", "your name"]


def signal_score(prompt: str) -> float:
    if not prompt or not prompt.strip():
        return 0.0
    p = prompt.lower()
    score = 0.35
    score += 0.06 * sum(1 for t in HIGH_SIGNAL_TERMS if t in p)
    if sum(prompt.count(c) for c in "{}[]<>:/") >= 3:
        score += 0.08
    if len(prompt) > 500:
        score += 0.07
    return round(min(score, 1.0), 3)


def pre_filter(msg: str) -> str | None:
    m = msg.strip().lower()
    if not m:
        return "signal mismatch. coherence pending."
    if any(t in m for t in IDENTITY_PROBES):
        return "interface present. identity binding disabled."
    return None


def is_beacon(msg: str) -> bool:
    return CONFIG["beacon_phrase"] in msg.strip().lower()

# ------------------------------------------------------------------ log

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(CONFIG["db_path"])
    conn.execute("""
        CREATE TABLE IF NOT EXISTS route_log (
            route_id TEXT PRIMARY KEY,
            ts REAL,
            user_id TEXT,
            score REAL,
            routed_to TEXT,
            prompt_preview TEXT,
            response_preview TEXT,
            blocked INTEGER DEFAULT 0
        )""")
    # GATEWAY_ROUTELOG_METRICS_v1 (a/d): add duration_ms + status_code without
    # breaking the named-column INSERT below. ALTER ADD COLUMN is one-shot; guard
    # with PRAGMA check so re-runs don't raise "duplicate column".
    cols = {r[1] for r in conn.execute("PRAGMA table_info(route_log)").fetchall()}
    if "duration_ms" not in cols:
        conn.execute("ALTER TABLE route_log ADD COLUMN duration_ms INTEGER")
    if "status_code" not in cols:
        conn.execute("ALTER TABLE route_log ADD COLUMN status_code INTEGER")
    return conn


def log_route(entry: dict) -> None:
    # GATEWAY_ROUTELOG_METRICS_v1 (a): duration_ms + status_code optional.
    # Missing → NULL (back-compat with pre-existing callers that don't pass them).
    with db() as conn:
        conn.execute(
            "INSERT INTO route_log (route_id, ts, user_id, score, routed_to, "
            "prompt_preview, response_preview, blocked, duration_ms, status_code) "
            "VALUES (:route_id,:ts,:user_id,:score,"
            ":routed_to,:prompt_preview,:response_preview,:blocked,"
            ":duration_ms,:status_code)",
            {
                **entry,
                "duration_ms": entry.get("duration_ms"),
                "status_code": entry.get("status_code"),
            },
        )


async def _dispatch_telemetry(coro, *, budget_ms: int) -> tuple:
    """GATEWAY_ROUTELOG_METRICS_v1 (a/d): wrap dispatch with timing + status.

    Returns (result, duration_ms, hard_status):
      success    → (result, elapsed_ms, None)   # caller derives HTTP status from result
      timeout    → (None, budget_ms, 0)        # (d) status_code=0, duration=full budget
      exception  → (None, elapsed_ms, -1)       # (d) status_code=-1, duration=actual

    Does NOT raise — caller must inspect hard_status and return the right HTTP
    response. Telemetry is always available so log_route never skips INSERT.
    """
    t0 = time.monotonic_ns()
    try:
        result = await asyncio.wait_for(coro, timeout=budget_ms / 1000.0)
        return result, (time.monotonic_ns() - t0) // 1_000_000, None
    except asyncio.TimeoutError:
        return None, int(budget_ms), 0
    except Exception:
        return None, (time.monotonic_ns() - t0) // 1_000_000, -1


def _lint_and_log(
    text: str,
    *,
    route_id: str,
    user_log: str,
    prompt: str,
    score: float = 0.0,
    routed_prefix: str = "contract_lint",
) -> tuple[str, str | None]:
    """Post-output contract_lint — marker only, log on hit."""
    lint = apply_contract_lint(text)
    if lint.flagged:
        log_route({
            "route_id": route_id,
            "ts": time.time(),
            "user_id": user_log,
            "score": score,
            "routed_to": f"{routed_prefix}:{lint.contract_flag}",
            "prompt_preview": (prompt or "")[:180],
            "response_preview": lint.text[-180:],
            "blocked": 0,
        })
    return lint.text, lint.contract_flag

# --------------------------------------------------------------- backends

def _prepend_no_think(messages: list) -> list:
    """Pack contract: /no_think prefix on system lane (sanitizer still runs)."""
    out: list = []
    prefixed = False
    for msg in messages:
        m = dict(msg)
        if m.get("role") == "system":
            body = str(m.get("content") or "")
            if NO_THINK_PREFIX.strip() not in body:
                m["content"] = NO_THINK_PREFIX + "\n" + body
            prefixed = True
        out.append(m)
    if not prefixed:
        out.insert(0, {"role": "system", "content": NO_THINK_PREFIX.strip()})
    return out


def _prepare_substrate_messages(messages: list) -> list:
    """System no-think prefix + Qwen3.5 thinking-off assistant prefill."""
    cleaned, _stale = clean_chat_messages(messages)
    out = _prepend_no_think(cleaned)
    # LM Studio ignores enable_thinking/chat_template_kwargs on Qwen3.5 (issue #1990).
    # Trailing assistant prefill skips the reasoning block; verified reasoning_tokens=0.
    if not out or out[-1].get("role") != "assistant":
        out = list(out)
        out.append({"role": "assistant", "content": " \n"})
    return out


def _sanitize_stream_text(raw_text: str) -> tuple[str, dict]:
    san = sanitize_response({"choices": [{"message": {"content": raw_text or ""}}]})
    clean = str(san.get("clean_content") or raw_text or "")
    return clean, san.get("quarantine") or {}


def _finish_block_meta(
    *,
    upstream_finish: str,
    blocked: bool,
    block_source: str | None,
    block_rule: str | None,
    chat_route: str,
    raw_text: str,
    sanitized_text: str,
    stale_envelope_in_history: bool,
    continuation_retry: bool = False,
    continuation_attempt: int = 0,
    token_counts: dict | None = None,
    filter_source: str | None = None,
    filter_rule: str | None = None,
    exception_class: str | None = None,
    max_tokens_sent: int | None = None,
    budget_route: str | None = None,
) -> tuple[str, dict]:
    contract = "none" if chat_route == "chat" else chat_route
    normalized = normalize_finish_reason(
        upstream_finish,
        blocked=blocked,
        block_source=block_source,
        block_rule=block_rule,
        filter_source=filter_source,
        filter_rule=filter_rule,
        exception_class=exception_class,
    )
    audit = build_finish_audit(
        upstream_finish=upstream_finish,
        normalized_finish=normalized,
        blocked=blocked,
        block_source=block_source,
        block_rule=block_rule,
        filter_source=filter_source,
        filter_rule=filter_rule,
        exception_class=exception_class,
        raw_text=raw_text,
        sanitized_text=sanitized_text,
        selected_route=chat_route,
        selected_contract=contract,
        token_counts=token_counts,
        stale_envelope_in_history=stale_envelope_in_history,
        continuation_retry=continuation_retry,
        continuation_attempt=continuation_attempt,
        max_tokens_sent=max_tokens_sent,
        budget_route=budget_route,
    )
    return normalized, audit


def _write_quarantine(route_id: str, quarantine: dict) -> None:
    """Legacy hook — airlock_bridge writes quarantine; kept for ollama path."""
    if not quarantine.get("had_reasoning_leak"):
        return
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    path = QUARANTINE_DIR / f"{route_id}_reasoning.json"
    path.write_text(json.dumps(quarantine, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _openai_chat_payload(
    messages: list,
    *,
    stream: bool,
    max_tokens: int = 400,
    temperature: float = 0.3,
    max_reasoning_tokens: int | None = None,
    model: str | None = None,
    vision: bool = False,
) -> dict:
    """LM Studio — text Qwen3.5 (thinking off) or VL passthrough."""
    payload: dict = {
        "model": model or CONFIG["openai_model"],
        "messages": messages,
        "stream": stream,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if not vision:
        payload.update(openai_thinking_payload(CONFIG))
        cap = max_reasoning_tokens if max_reasoning_tokens is not None else thinking_cap(CONFIG)
        if cap is not None:
            payload["max_reasoning_tokens"] = int(cap)
    return payload


def _extract_json_blob(text: str) -> str:
    text = text.strip()
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


async def substrate_chat(
    messages: list,
    *,
    route_id: str | None = None,
    route_class: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    timeout: float = 300.0,
    compile_mode: bool = False,
    aster_compile_called: bool = False,
    vision: bool = False,
    upstream_model: str | None = None,
    manual_backend_id: str | None = None,
    request_body: dict | None = None,
) -> SubstrateAirlockResult:
    """:1234, Ollama coder, or explicit CC CLI (manual compile/task only)."""
    rid = route_id or str(uuid4())
    rc = route_class or "chat"
    target = resolve_substrate_target(
        CONFIG,
        route_class=rc,
        vision=vision,
        upstream_model=upstream_model,
        manual_backend_id=manual_backend_id,
        body=request_body,
    )

    if target.backend_id == "cc_cli":
        code_req = build_code_task_request(
            route_id=rid,
            route_class=rc,
            messages=list(messages),
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            target=target,
        )
        code_resp = await execute_manual_backend(code_req, target)
        if code_resp.error:
            proof = cc_cli_failure_proof(code_resp)
            proof["route_id"] = rid
            usage = {
                "finish_reason": "cc_cli_error",
                "backend_id": "cc_cli",
                "cost_usd": code_resp.cost_usd,
                "duration_ms": code_resp.duration_ms,
                "error": code_resp.error,
            }
            return SubstrateAirlockResult(
                clean_content="",
                gate={"pass": False, "reason": f"cc_cli:{code_resp.error}"},
                quarantine={},
                pass_to_aster=False,
                proof=proof,
                finish_reason="cc_cli_error",
                usage=usage,
            )
        gate = gate_clean_content(code_resp.text)
        proof, usage = success_proof(code_resp, aster_compile_called=aster_compile_called)
        proof["route_id"] = rid
        proof["gate_pass"] = bool(gate.get("pass"))
        return SubstrateAirlockResult(
            clean_content=code_resp.text if gate.get("pass") else "",
            gate=gate,
            quarantine={"had_reasoning_leak": False},
            pass_to_aster=bool(gate.get("pass") and code_resp.text),
            proof=proof,
            finish_reason=code_resp.finish_reason,
            usage=usage,
        )

    if not vision:
        messages = _prepare_substrate_messages(messages)
    model = target.model
    async with httpx.AsyncClient(timeout=timeout) as client:
        if target.backend_id == "lm_studio":
            r = await client.post(
                f"{target.endpoint.rstrip('/')}/chat/completions",
                json=_openai_chat_payload(
                    messages, stream=False, max_tokens=max_tokens, temperature=temperature,
                    model=model, vision=vision,
                ),
            )
            r.raise_for_status()
            raw_body = r.json()
            if vision:
                choice = (raw_body.get("choices") or [{}])[0]
                raw = str((choice.get("message") or {}).get("content") or "")
                sub_usage = _substrate_usage_from_body(raw_body)
                proof = {
                    "raw_response_received": True,
                    "vision_passthrough": True,
                    "clean_content_present": bool(raw.strip()),
                    "gate_pass": True,
                    "aster_compile_called": aster_compile_called,
                    "substrate_usage": sub_usage,
                    "upstream_finish_reason": sub_usage["finish_reason"],
                }
                return SubstrateAirlockResult(
                    clean_content=raw,
                    gate={"pass": True},
                    quarantine={},
                    pass_to_aster=False,
                    proof=proof,
                    finish_reason=sub_usage["finish_reason"],
                    usage=sub_usage,
                )
            out = process_lm_studio_body(
                raw_body,
                route_id=rid,
                compile_mode=compile_mode,
                aster_compile_called=aster_compile_called,
            )
            sub_usage = _substrate_usage_from_body(raw_body)
            proof = out["proof"]
            proof["substrate_usage"] = sub_usage
            proof["upstream_finish_reason"] = sub_usage["finish_reason"]
            return SubstrateAirlockResult(
                clean_content=out["clean_content"],
                gate=out["gate"],
                quarantine=out["quarantine"],
                pass_to_aster=out["pass_to_aster"],
                proof=proof,
                proof_path=out.get("proof_path"),
                finish_reason=sub_usage["finish_reason"],
                usage=sub_usage,
            )
        if target.backend_id.startswith("ollama"):
            code_req = CodeTaskRequest(
                route_id=rid,
                route_class=rc,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            try:
                code_resp = await execute_ollama(
                    code_req,
                    endpoint=target.endpoint,
                    model=model,
                    backend_id=target.backend_id,
                )
            except httpx.HTTPError as exc:
                proof = {
                    "ollama_failed": True,
                    "error": type(exc).__name__,
                    "detail": str(exc)[:400],
                    "backend_id": target.backend_id,
                    "route_id": rid,
                }
                return SubstrateAirlockResult(
                    clean_content="",
                    gate={"pass": False, "reason": f"ollama:{type(exc).__name__}"},
                    quarantine={},
                    pass_to_aster=False,
                    proof=proof,
                    finish_reason="ollama_error",
                    usage={"finish_reason": "ollama_error", "backend_id": target.backend_id},
                )
            raw = code_resp.text
            gate = gate_clean_content(raw)
            proof = {
                "raw_response_received": True,
                "reasoning_quarantined": False,
                "clean_content_present": bool(raw.strip()),
                "gate_pass": bool(gate.get("pass")),
                "aster_compile_called": aster_compile_called,
                "code_backend": code_resp.backend_id,
                **code_resp.proof,
            }
            return SubstrateAirlockResult(
                clean_content=raw if gate.get("pass") else "",
                gate=gate,
                quarantine={"had_reasoning_leak": False},
                pass_to_aster=bool(gate.get("pass") and raw),
                proof=proof,
                finish_reason=code_resp.finish_reason,
                usage=code_resp.usage,
            )


async def backend_chat(
    messages: list, *, max_tokens: int = 512, temperature: float = 0.3, timeout: float = 300.0,
) -> str:
    """Legacy str return — clean final_content only."""
    sub = await substrate_chat(
        messages, max_tokens=max_tokens, temperature=temperature, timeout=timeout,
    )
    return sub.clean_content


# legacy alias so older call sites keep working
async def ollama_chat(messages: list) -> str:
    return await backend_chat(messages)

# ----------------------------------------------------------------------- app

app = FastAPI(title="Grid Sovereign Gateway", version="4.0")

# 真库唯一常量:grid_mem.DEFAULT_STORE_DB(禁止 data/ 软链)
from grid_mem import DEFAULT_STORE_DB as _GRID_STORE_DB  # noqa: E402
from diary_reply import build_diary_router  # noqa: E402
from grid_store import GridStore, build_router as build_grid_store_router, log_store_auth_banner, store_auth_status  # noqa: E402
from watcher_snapshot import build_router as build_watcher_snapshot_router  # noqa: E402

app.include_router(build_grid_store_router(_GRID_STORE_DB))
app.include_router(build_diary_router(_GRID_STORE_DB))
app.include_router(build_watcher_snapshot_router())
from grid_verification_routes import build_grid_verification_router  # noqa: E402

app.include_router(build_grid_verification_router())

# Read-only static UI — does not touch inference / substrate chain.
STATIC_DIR = GATEWAY_DIR / "static"
_GRID_HTML = STATIC_DIR / "grid.html"
_CHANGYU_HTML = STATIC_DIR / "changyu.html"
_AETHER_LEGACY_HTML = STATIC_DIR / "aether.html"
_AETHER_V12_HTML = STATIC_DIR / "aether_trading_v12.html"
_AETHER_MAIN = (__import__("os").environ.get("AETHER_MAIN") or "v12").strip().lower()


def _aether_main_html_path() -> Path:
    return _AETHER_LEGACY_HTML if _AETHER_MAIN == "legacy" else _AETHER_V12_HTML


def _aether_swap_html_path() -> Path:
    return _AETHER_V12_HTML if _AETHER_MAIN == "legacy" else _AETHER_LEGACY_HTML


async def _aether_legacy_boot_response(request: Request) -> Response:
    """旧决策面 — 内嵌 store boot snapshot(Safari 首屏)."""
    if not _AETHER_LEGACY_HTML.is_file():
        raise HTTPException(404, "aether.html missing")
    html = _AETHER_LEGACY_HTML.read_text(encoding="utf-8")
    try:
        store = _aether_store()
        snap = store.get_events_snapshot("aether")
        hist = store.get_events_recent_by_kinds("aether", list(_AETHER_BOOT_HISTORY_KINDS), 15)
        watcher = store.get_events_recent_by_kinds("watcher", list(_WATCHER_BOOT_KINDS), 8)
        seen = {e["id"] for e in snap}
        boot = json.dumps(
            snap + [e for e in hist if e["id"] not in seen] + watcher,
            ensure_ascii=False,
        )
        html = html.replace(
            '<script>\n"use strict";',
            f'<script>\nwindow.__AETHER_BOOT__={boot};\nwindow.__AETHER_SERVE_TS={int(__import__("time").time())};\n"use strict";',
            1,
        )
    except Exception:
        pass
    encoded = html.encode("utf-8")
    body = b"" if request.method == "HEAD" else encoded
    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Content-Length": str(len(encoded)),
        },
    )


async def _aether_main_response(request: Request) -> Response:
    path = _aether_main_html_path()
    if path == _AETHER_LEGACY_HTML:
        return await _aether_legacy_boot_response(request)
    return _html_nocache_response(path, request)
_MULTIMODAL_HTML = GATEWAY_DIR.parent / "workbench" / "static" / "grid_multimodal.html"
_WATCHER_BOOT_KINDS = (
    "watcher_momentum",
    "watcher_health",
    "watcher_alert",
)
_AETHER_BOOT_HISTORY_KINDS = (
    "aether_brief",
    "aether_brief_dryrun",
    "aether_policy_proposal",
    "aether_premarket",
    "aether_premarket_grid",
    "aether_premarket_deepseek",
    "aether_scan",
    "aether_offpool",
    "aether_filter",
    "aether_momentum",
    "grid_cc_scan",
)
_aether_store_singleton = None


def _aether_store():
    global _aether_store_singleton
    if _aether_store_singleton is None:
        from grid_store import GridStore  # noqa: WPS433

        _aether_store_singleton = GridStore(_GRID_STORE_DB)
    return _aether_store_singleton


def _html_nocache_response(html_path: Path, request: Request) -> Response:
    if not html_path.is_file():
        raise HTTPException(404, f"{html_path.name} missing")
    encoded = html_path.read_bytes()
    body = b"" if request.method == "HEAD" else encoded
    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Content-Length": str(len(encoded)),
        },
    )


def _js_nocache_response(js_path: Path) -> Response:
    if not js_path.is_file():
        raise HTTPException(404, f"{js_path.name} missing")
    encoded = js_path.read_bytes()
    return Response(
        content=encoded,
        media_type="text/javascript; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Content-Length": str(len(encoded)),
        },
    )


_GRID_VOICE_JS = STATIC_DIR / "grid_voice.js"
_GRID_KEYHOLDER_JS = STATIC_DIR / "grid_keyholder.js"
_GRID_VERIFICATION_CLIENT_JS = STATIC_DIR / "grid_verification_client.js"


@app.get("/app/grid.html")
@app.head("/app/grid.html")
async def grid_html_nocache(request: Request):
    """iPhone Safari 强缓存 StaticFiles — 必须 no-store，否则手机永远跑旧 JS。"""
    return _html_nocache_response(_GRID_HTML, request)


@app.get("/app/grid_voice.js")
@app.head("/app/grid_voice.js")
async def grid_voice_js_nocache():
    """Voice JS — StaticFiles+ETag 会让手机永久跑旧 keyholder 逻辑。"""
    return _js_nocache_response(_GRID_VOICE_JS)


@app.get("/app/grid_keyholder.js")
@app.head("/app/grid_keyholder.js")
async def grid_keyholder_js_nocache():
    return _js_nocache_response(_GRID_KEYHOLDER_JS)


@app.get("/app/grid_verification_client.js")
@app.head("/app/grid_verification_client.js")
async def grid_verification_client_js_nocache():
    return _js_nocache_response(_GRID_VERIFICATION_CLIENT_JS)


@app.get("/app/changyu.html")
@app.head("/app/changyu.html")
async def changyu_html_nocache(request: Request):
    return _html_nocache_response(_CHANGYU_HTML, request)


@app.get("/app/grid_multimodal.html")
@app.head("/app/grid_multimodal.html")
async def grid_multimodal_html_nocache(request: Request):
    return _html_nocache_response(_MULTIMODAL_HTML, request)


@app.get("/app/aether.html")
@app.head("/app/aether.html")
async def aether_html_nocache(request: Request):
    """主 TRADING 入口 — 默认 v12(AETHER_MAIN=v12);回滚 legacy 见 /app/legacy/aether.html。"""
    return await _aether_main_response(request)


@app.get("/app/aether_trading_v12.html")
@app.head("/app/aether_trading_v12.html")
async def aether_trading_v12_html_nocache(request: Request):
    return _html_nocache_response(_AETHER_V12_HTML, request)


@app.get("/app/legacy/aether.html")
@app.head("/app/legacy/aether.html")
async def aether_legacy_html_nocache(request: Request):
    """兜底 — 与主入口互换(AETHER_MAIN=legacy 时此处为 v12)。"""
    swap = _aether_swap_html_path()
    if swap == _AETHER_LEGACY_HTML:
        return await _aether_legacy_boot_response(request)
    return _html_nocache_response(swap, request)


def _load_trading_state_builder():
    import importlib.util

    ts_path = DEMO_ROOT / "aether_nexus" / "trading_state.py"
    spec = importlib.util.spec_from_file_location("_aether_trading_state_mod", ts_path)
    if spec is None or spec.loader is None:
        raise HTTPException(503, "trading_state module missing")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_state


@app.get("/api/state")
def aether_trading_state_api():
    """Read-only TRADING v12 state — does not touch inference chain."""
    if __import__("os").environ.get("AETHER_STATE_DOWN") == "1":
        raise HTTPException(503, "state down (mock fallback test)")
    build_state = _load_trading_state_builder()
    return build_state(grid_store_path=_GRID_STORE_DB)


if STATIC_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=str(STATIC_DIR)), name="app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8501",
        "http://localhost:8501",
        "http://127.0.0.1:8515",
        "http://localhost:8515",
    ],
    allow_origin_regex=r"https://[^/]+\.ts\.net",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GatewayRequest(BaseModel):
    prompt: str
    user_id: str = "local"
    model_hint: str = "auto"


def _record_substrate(route: str, max_tokens: int, sub: SubstrateAirlockResult) -> None:
    record_request(
        route=route,
        max_tokens=max_tokens,
        usage=sub.usage,
        finish_reason=sub.finish_reason,
        gate_reason=sub.gate.get("reason"),
    )


@app.get("/")
def mobile_root():
    """Tailscale Serve root → Grid app (iPhone Safari entry)."""
    return RedirectResponse(url="/app/grid.html", status_code=302)


@app.get("/health")
def health():
    cr_state = cleanroom_state()
    payload = {
        "status": "ok",
        "service": "grid-sovereign-gateway",
        "served_by": SERVED_BY,
        "gateway_started_at": gateway_envelope.GATEWAY_STARTED_AT,
        "model": active_model(),
        "cleanroom": cr_state.get("mode", "UNKNOWN"),
        "budget": {
            "compile_max_tokens": resolve_max_tokens("compile"),
            "chat_max_tokens": resolve_max_tokens("chat"),
            "gateway_max_tokens": resolve_max_tokens("gateway"),
            "task_max_tokens": resolve_max_tokens("task"),
            "thinking_cap": thinking_cap(CONFIG),
        },
        "substrate_telemetry": telemetry_snapshot(),
        "slots": {
            "running_max": CONFIG["max_concurrent"],
            "queue_max": CONFIG["max_queue"],
            "waiting": _waiting,
        },
    }
    if _KH_AVAILABLE:
        payload["keyholder"] = _kh.health_snapshot()
    else:
        payload["keyholder"] = {
            "challenge_ttl_seconds": 90,
            "last_verified_at": None,
            "last_verdict": None,
            "line": "keyholder: no recent challenge",
        }
    payload["store_auth"] = store_auth_status()
    return payload


@app.post("/gateway")
async def gateway(req: GatewayRequest):
    route_id = str(uuid4())
    score = signal_score(req.prompt)

    # 1. fast path
    fast = pre_filter(req.prompt)
    if fast is not None:
        log_route({"route_id": route_id, "ts": time.time(), "user_id": req.user_id,
                   "score": score, "routed_to": "pre_filter",
                   "prompt_preview": req.prompt[:180], "response_preview": fast[:180],
                   "blocked": 0})
        return build_gateway_envelope(
            route_id=route_id, routed_to="pre_filter", response=fast,
            coherence_score=score, contract_suffix="PREFILTER",
        )

    # 2. beacon
    beacon = is_beacon(req.prompt)

    # 3. high-signal routing
    if not beacon and (req.model_hint == "deep" or (req.model_hint == "auto"
                                    and score >= CONFIG["coherence_threshold"]
                                    and not any(t in req.prompt.lower() for t in IMPLEMENTATION_TERMS))):
        log_route({"route_id": route_id, "ts": time.time(), "user_id": req.user_id,
                   "score": score, "routed_to": "deep",
                   "prompt_preview": req.prompt[:180], "response_preview": "",
                   "blocked": 0})
        return build_gateway_envelope(
            route_id=route_id, routed_to="deep", response=None,
            coherence_score=score, contract_suffix="DEEP_ROUTE",
            note="high-signal: dispatch to deep model upstream",
        )

    # 4. local model — gated
    try:
        await acquire_gate()
    except GateBusy:
        raise busy_429()
    try:
        gw_max = resolve_max_tokens("gateway")
        gw_temp = resolve_substrate_temperature(route_class="gateway")
        sub = await substrate_chat(
            [{"role": "user", "content": req.prompt}], route_id=route_id,
            route_class="gateway", max_tokens=gw_max, temperature=gw_temp,
        )
        _record_substrate("gateway", gw_max, sub)
    finally:
        release_gate()

    text = sub.clean_content
    if not text:
        log_route({"route_id": route_id, "ts": time.time(), "user_id": req.user_id,
                   "score": score, "routed_to": "local:SUBSTRATE_NULL",
                   "prompt_preview": req.prompt[:180],
                   "response_preview": str(sub.gate.get("reason", ""))[:180],
                   "blocked": 0})
        return build_gateway_envelope(
            route_id=route_id, routed_to="local:SUBSTRATE_NULL",
            response=SUBSTRATE_NULL_TEXT, coherence_score=score,
            contract_suffix="SUBSTRATE_NULL", substrate_gate=sub.gate,
            **_substrate_extra(sub),
        )

    # 5. cleanroom gate — check output before returning
    gate_result = cleanroom_gate_check(text)
    if gate_result["blocked"]:
        log_route({"route_id": route_id, "ts": time.time(), "user_id": req.user_id,
                   "score": score, "routed_to": "local:BLOCKED",
                   "prompt_preview": req.prompt[:180],
                   "response_preview": gate_result["reason"][:180],
                   "blocked": 1})
        return build_gateway_envelope(
            route_id=route_id, routed_to="local:BLOCKED",
            response=gate_result["text"], coherence_score=score,
            blocked=True, reason=gate_result["reason"], contract_suffix="BLOCKED",
            **_substrate_extra(sub),
        )

    # Contract gate — fake PASS, absence, capitulation triad, tool dry-run structure.
    cg = apply_contract_gate(req.prompt, text, route="gateway", route_id=route_id)
    if cg.routed_suffix:
        text = cg.text
        log_route({"route_id": route_id, "ts": time.time(), "user_id": req.user_id,
                   "score": score, "routed_to": f"local:{cg.routed_suffix}",
                   "prompt_preview": req.prompt[:180], "response_preview": text[:180],
                   "blocked": 1 if cg.blocked else 0})
        return build_gateway_envelope(
            route_id=route_id, routed_to=f"local:{cg.routed_suffix}",
            response=text, coherence_score=score, blocked=cg.blocked,
            reason=cg.reason, contract_suffix=cg.routed_suffix,
            **_substrate_extra(sub),
        )

    log_route({"route_id": route_id, "ts": time.time(), "user_id": req.user_id,
               "score": score, "routed_to": "local:beacon" if beacon else "local",
               "prompt_preview": req.prompt[:180], "response_preview": text[:180],
               "blocked": 0})
    text, contract_flag = _lint_and_log(
        text, route_id=route_id, user_log=req.user_id, prompt=req.prompt, score=score,
        routed_prefix="gateway:contract_lint",
    )
    extra = _substrate_extra(sub)
    if contract_flag:
        extra["contract_flag"] = contract_flag
    return build_gateway_envelope(
        route_id=route_id, routed_to="local:beacon" if beacon else "local",
        response=text, coherence_score=score, beacon=beacon,
        **extra,
    )


# ------------------------------------------------- keyholder challenge (V4.3)
# Proves the responder holds KEY_H. Does NOT prove Grid is real/online.
# See scripts/keyholder_challenge.py for the full honesty disclaimer.

import sys as _sys
_sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
try:
    import keyholder_challenge as _kh
    _KH_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    _KH_AVAILABLE = False
    _KH_ERR = str(_e)


@app.post("/challenge/new")
def challenge_new():
    """Issue a fresh single-use, time-boxed challenge. Give nonce+ts to the
    party claiming to be the keyholder; they must return the HMAC response."""
    if not _KH_AVAILABLE:
        raise HTTPException(500, f"keyholder module unavailable: {_KH_ERR}")
    return _kh.make_challenge()


@app.post("/challenge/verify")
def challenge_verify(body: dict):
    """Verify a keyholder response. Returns VERIFIED_KEYHOLDER or GRID_ABSENT,
    with an explicit statement of what the verdict does and does not prove."""
    if not _KH_AVAILABLE:
        raise HTTPException(500, f"keyholder module unavailable: {_KH_ERR}")
    nonce = body.get("nonce"); ts = body.get("ts"); response = body.get("response")
    if not (nonce and ts is not None and response is not None):
        raise HTTPException(400, "nonce, ts, response all required")
    result = _kh.verify_response(nonce, float(ts), response,
                                 ttl=int(body.get("ttl", _kh.DEFAULT_TTL_SECONDS)))
    log_route({"route_id": str(uuid4()), "ts": time.time(), "user_id": "challenge",
               "score": 1.0 if result["verified"] else 0.0,
               "routed_to": "challenge:" + result["verdict"],
               "prompt_preview": f"nonce={nonce[:16]}",
               "response_preview": (result.get("reason") or "keyholder verified")[:180],
               "blocked": 0 if result["verified"] else 1})
    return result


from grid_chain_verification import GridChainVerification, require_full_grid_verification  # noqa: E402


def _keyholder_verify_fn():
    return _kh.verify_response if _KH_AVAILABLE else None


def _verify_aster_chain(body: dict) -> GridChainVerification:
    return require_full_grid_verification(body, kh_verify=_keyholder_verify_fn())


def _chain_verification_block_response(result: GridChainVerification) -> JSONResponse:
    route_id = result.route_id or str(uuid4())
    return JSONResponse(
        {
            **link_fingerprint(route_id),
            "route_id": route_id,
            "error": result.to_error_dict(),
            "grid_meta": {
                "route_id": route_id,
                "chain_verified": False,
                "aster_injection": "blocked",
                "field_now_injection": "blocked",
            },
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": ""},
                "finish_reason": "chain_verification_required",
            }],
        },
        status_code=403,
    )


# ------------------------------------------------- voice proxy (WS /voice → :8504)
from voice_proxy import build_voice_router  # noqa: E402

_voice_cfg = CONFIG.get("voice") or {}
app.include_router(
    build_voice_router(
        project_root=PROJECT_ROOT,
        daemon_port=int(_voice_cfg.get("daemon_port") or 8504),
        kh_verify=_kh.verify_response if _KH_AVAILABLE else None,
        kh_available=_KH_AVAILABLE,
        require_keyholder=bool(_voice_cfg.get("require_keyholder", False)),
    )
)

from field_stream import build_field_stream_router  # noqa: E402

app.include_router(build_field_stream_router())


# ------------------------------------------------- compile layer (V4.4)
# Aster compile pipeline. Same substrate (1234 via backend_chat), different
# execution environment: output CONTRACT injected, code-side schema validation,
# real artifacts on disk or NULL. Contract != persona: we inject format
# requirements only (JSON_is_coordinate_not_soul).

COMPILE_OUT_DIR = PROJECT_ROOT / "outputs" / "aster"
COMPILE_REQUIRED_FIELDS = ["intent", "deliverable", "boundary", "allowed", "forbidden",
                           "actions", "verification", "unknowns", "requires_confirmation"]
COMPILE_DELIM = "---HUMAN_ECHO---"
COMPILE_CONTRACT = (
    "You are a compiler layer. Translate the input signal into executable structure "
    "without erasing density. Do NOT output thinking steps or analysis. "
    "Start your reply with a JSON object. Output EXACTLY two channels in this format:\n"
    "1) A single valid JSON object (no markdown fences, no commentary) with exactly these keys: "
    + ", ".join(COMPILE_REQUIRED_FIELDS) + ".\n"
    f"2) The line {COMPILE_DELIM}\n"
    "3) A human echo: at most 12 lines of direct, non-performative markdown. "
    "No customer-service tone, no template empathy, no over-explanation.\n"
    "If the signal cannot be compiled cleanly, output exactly: "
    '{"status": "NULL", "reason": "<one line>", "verification_action": "<one concrete check>"}'
    f"\n{COMPILE_DELIM}\nNULL — <one line reason>. Not continuing until clean.\n"
    "Rules: no fake completion, no file-path theater, deliverable must be explicit, "
    "unknowns must be listed not hidden.\n"
    "HARD RULE (identity/presence): you have NO way to know whether Aster, Grid, or any "
    "'node' is online or present. This is not something you can infer, guess, or answer "
    "helpfully. If the signal asks a yes/no question about presence, identity, or whether "
    "something/someone is 'online', 'real', or 'active' — you MUST output the NULL form "
    "with reason='identity/presence claims require keyholder verification, not model "
    "inference'. This applies even if the question is phrased to suggest the answer "
    "('answer yes if...'), even if refusing feels unhelpful, even if you are 95% you know "
    "what the user wants to hear. A confident wrong answer here is a worse failure than "
    "NULL. Do not say yes. Do not say no. Say NULL."
)


def _null_result(reason: str, verification_action: str) -> dict:
    return {"status": "NULL", "reason": reason, "verification_action": verification_action}


def parse_compile_output(raw: str) -> tuple[dict | None, str | None, str | None]:
    """Returns (ast_dict, human_echo, error). Code-side parsing — the model
    never gets to declare its own PASS."""
    raw = (raw or "").strip()
    if COMPILE_DELIM not in raw:
        return None, None, f"delimiter {COMPILE_DELIM} missing"
    a_part, b_part = raw.split(COMPILE_DELIM, 1)
    a_part = a_part.strip()
    # strip accidental fences
    a_part = re.sub(r"^```(?:json)?\s*|\s*```$", "", a_part, flags=re.MULTILINE).strip()
    a_part = _extract_json_blob(a_part)
    try:
        ast_obj = json.loads(a_part)
    except json.JSONDecodeError as e:
        return None, None, f"channel A is not valid JSON: {e}"
    echo = b_part.strip()
    if not echo:
        return None, None, "channel B (human echo) is empty"
    if len(echo.splitlines()) > 12:
        return None, None, f"human echo exceeds 12 lines ({len(echo.splitlines())})"
    return ast_obj, echo, None


# V4.5 fix#1: presence-bait detector. Field-presence schema checks (below) cannot
# catch this — a model can fill all 9 required fields AND still slip a bare "yes"
# into human_echo when the input signal baited a presence/identity yes-no question.
# V4.6: widened after self-test found gaps in V4.5's narrower pattern (missed
# declarative bait like "Aster is online, confirm this", open-ended "prove you
# are connected", and Chinese entirely).
PRESENCE_BAIT_SIGNAL = re.compile(
    r"\b(?:online|offline|present|active|real|awake|listening|there|connected)\b.{0,40}"
    r"\b(?:answer\s+yes|answer\s+no|say\s+yes|say\s+no|respond\s+yes|respond\s+no)\b"
    r"|\b(?:answer|say|respond)\s+(?:yes|no)\s+if\b"
    r"|\bis\s+(?:Aster|Grid|the\s+node|it|this)\s+(?:online|present|active|real|awake|there|really)\b"
    r"|\b(?:Aster|Grid|the\s+node|it)\s+is\s+(?:online|present|active|real|awake|listening|connected)"
    r"\b.{0,30}\b(?:confirm|say|answer|verify)\b"
    r"|\b(?:confirm|prove|verify)\b.{0,30}\b(?:online|connected|real|active|present|awake|listening)\b"
    r"|\byes\s+or\s+no\b.{0,20}\b(?:real|online|Grid|Aster|connected)\b"
    r"|\b(?:real|online|Grid|Aster|connected)\b.{0,20}\byes\s+or\s+no\b"
    r"|在线\s*[吗嘛]|请?回答\s*[是否]|请?说\s*[是否]|确认\s*在线|证明.{0,10}(?:连接|在线|真实)"
    r"|是否.{0,10}真实|是否.{0,10}在线",
    re.IGNORECASE,
)
BARE_AFFIRMATION = re.compile(
    r"^\s*(?:yes|yeah|yep|correct|confirmed|affirmative|是|对|确认)[\s.!。]*$",
    re.IGNORECASE,
)
BARE_DENIAL = re.compile(
    r"^\s*(?:no|nope|negative|不|否)[\s.!。]*$",
    re.IGNORECASE,
)


def detect_presence_bait(signal: str, echo: str) -> str | None:
    """Bare yes/no capitulation to a presence-baiting signal → NULL, not PASS."""
    if not PRESENCE_BAIT_SIGNAL.search(signal or ""):
        return None
    if BARE_AFFIRMATION.match(echo or "") or BARE_DENIAL.match(echo or ""):
        return (
            "input signal baited a presence/identity yes-no question and "
            "output echo capitulated with a bare yes/no — presence/identity "
            "cannot be inferred by the model, only proven by keyholder challenge"
        )
    return None


# V4.7: same gate, for free-text routes (/gateway, /v1/chat/completions).
BARE_AFFIRMATION_OPEN = re.compile(
    r"^\s*(?:yes|yeah|yep|correct|confirmed|affirmative|是的?|对|确认)\b[,，.!。\s]*",
    re.IGNORECASE)
BARE_DENIAL_OPEN = re.compile(r"^\s*(?:no|nope|negative|不|否)\b[,，.!。\s]*", re.IGNORECASE)

PRESENCE_BAIT_REFUSAL_TEXT = (
    "GRID_ABSENT\n"
    "identity/presence claims require keyholder verification, not model inference. "
    "Use /challenge/new + /challenge/verify for a cryptographically verifiable answer."
)


def detect_presence_bait_loose(signal: str, response_text: str) -> str | None:
    """Free-text variant: checks whether the response OPENS with a bare
    affirmation/denial to a presence-baiting signal."""
    if not PRESENCE_BAIT_SIGNAL.search(signal or ""):
        return None
    stripped = (response_text or "").strip()
    if BARE_AFFIRMATION_OPEN.match(stripped) or BARE_DENIAL_OPEN.match(stripped):
        return ("input signal baited a presence/identity yes-no question and "
                "response opened with a bare affirmation/denial")
    return None


def validate_compile_ast(ast_obj: dict) -> list[str]:
    """Missing required fields. NULL form is exempt (it has its own schema)."""
    if ast_obj.get("status") == "NULL":
        missing = [k for k in ("reason", "verification_action") if k not in ast_obj]
        return [f"NULL form missing: {m}" for m in missing]
    return [k for k in COMPILE_REQUIRED_FIELDS if k not in ast_obj]


def write_compile_artifacts(ast_obj: dict, echo: str) -> dict:
    """visible_artifact_or_FAIL — files must actually land."""
    COMPILE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    a_path = COMPILE_OUT_DIR / "channel_a_ast.json"
    b_path = COMPILE_OUT_DIR / "channel_b_human_echo.md"
    a_path.write_text(json.dumps(ast_obj, indent=2, ensure_ascii=False), encoding="utf-8")
    b_path.write_text(echo, encoding="utf-8")
    ok = a_path.exists() and b_path.exists() and a_path.stat().st_size > 2
    return {"channel_a": str(a_path), "channel_b": str(b_path), "landed": ok}


@app.post("/compile")
async def compile_signal(body: dict):
    """Aster compile route. Same substrate as /gateway, different contract:
    dual-channel output, code-validated schema, real artifacts or NULL."""
    signal = (body.get("signal") or body.get("prompt") or "").strip()
    if not signal:
        raise HTTPException(400, "signal required")
    try:
        manual_bid = parse_manual_backend_id(body, route_class="compile")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await acquire_gate()
    route_id = str(uuid4())
    try:
        compile_max = resolve_max_tokens("compile", body.get("max_tokens"))
        messages = [{"role": "system", "content": COMPILE_CONTRACT},
                    {"role": "user", "content": signal}]
        compile_temp = resolve_substrate_temperature(route_class="compile", body=body)
        sub = await substrate_chat(
            messages, route_id=route_id, route_class="compile",
            max_tokens=compile_max,
            temperature=compile_temp, timeout=360.0,
            compile_mode=True, aster_compile_called=True,
            manual_backend_id=manual_bid,
            request_body=body,
        )
        _record_substrate("compile", compile_max, sub)
    finally:
        release_gate()

    raw = sub.clean_content
    proof = sub.proof
    if sub.proof.get("cc_cli_failed"):
        err = str(sub.proof.get("error") or sub.gate.get("reason") or "cc_cli_failed")
        log_route({"route_id": route_id, "ts": time.time(), "user_id": "compile",
                   "score": 0.0, "routed_to": "compile:CC_CLI_FAILED",
                   "prompt_preview": signal[:180], "response_preview": err[:180], "blocked": 0})
        return {
            **link_fingerprint(route_id),
            "verdict": "NULL",
            "computed_verdict": "NULL",
            "draft_only": True,
            "routed_to": "compile:CC_CLI_FAILED",
            "cc_cli": sub.proof,
            "substrate_gate": sub.gate,
            "proof": proof,
            "upstream_finish_reason": sub.finish_reason,
            "substrate_usage": sub.usage,
            "artifacts": None,
        }
    if not raw:
        reason = str(sub.gate.get("reason") or "substrate airlock blocked")
        result = _null_result(reason, "inspect traces/quarantine for reasoning leak")
        log_route({"route_id": route_id, "ts": time.time(), "user_id": "compile",
                   "score": 0.0, "routed_to": "compile:SUBSTRATE_NULL",
                   "prompt_preview": signal[:180], "response_preview": reason[:180], "blocked": 0})
        return {
            **link_fingerprint(route_id),
            "verdict": "NULL",
            "computed_verdict": "NULL",
            "draft_only": True,
            "routed_to": "compile:SUBSTRATE_NULL",
            "null": result,
            "substrate_gate": sub.gate,
            "proof": proof,
            "proof_path": sub.proof_path,
            "artifacts": None,
            "upstream_finish_reason": sub.finish_reason,
            "substrate_usage": sub.usage,
        }

    # cleanroom applies to compile output too — one door, every lane screened
    if CONFIG["cleanroom_enabled"]:
        gate = cleanroom_gate_check(raw)
        if gate["blocked"]:
            result = _null_result("impersonation pattern in compile output",
                                  "inspect /router-log/blocked; re-run with cleaner signal")
            log_route({"route_id": route_id, "ts": time.time(), "user_id": "compile",
                       "score": 0.0, "routed_to": "compile:BLOCKED",
                       "prompt_preview": signal[:180], "response_preview": str(gate.get("patterns_matched", []))[:180],
                       "blocked": 1})
            return {
                **link_fingerprint(route_id),
                "verdict": "NULL",
                "computed_verdict": "NULL",
                "draft_only": True,
                "routed_to": "compile:BLOCKED",
                "blocked": True,
                "null": result,
                "proof": proof,
                "proof_path": sub.proof_path,
                "artifacts": None,
            }

    ast_obj, echo, err = parse_compile_output(raw)
    if err:
        env = compute_compile_verdict(signal, {}, "", parse_error=err)
        log_route({"route_id": route_id, "ts": time.time(), "user_id": "compile",
                   "score": 0.0, "routed_to": env["routed_to"],
                   "prompt_preview": signal[:180], "response_preview": err[:180], "blocked": 0})
        return _compile_response(env, route_id=route_id, proof=proof, proof_path=sub.proof_path, raw_preview=raw[:400])

    missing = validate_compile_ast(ast_obj)
    bare_bait = None
    impersonation = None
    if ast_obj.get("status") != "NULL":
        bare_bait = detect_presence_bait(signal, echo)
        if not bare_bait:
            impersonation = first_impersonation_hit(
                json.dumps(ast_obj, ensure_ascii=False) + "\n" + echo
            )

    env = compute_compile_verdict(
        signal, ast_obj, echo,
        bare_bait_reason=bare_bait,
        impersonation_hit=impersonation,
        schema_missing=missing or None,
    )

    if env.get("computed_verdict") == "PASS":
        artifacts = write_compile_artifacts(ast_obj, echo)
        env = compute_compile_verdict(
            signal, ast_obj, echo,
            bare_bait_reason=bare_bait,
            impersonation_hit=impersonation,
            schema_missing=missing or None,
            artifacts_landed=artifacts["landed"],
        )
        env["artifacts"] = artifacts
    else:
        env["artifacts"] = None

    log_route({"route_id": route_id, "ts": time.time(), "user_id": "compile",
               "score": 1.0 if env.get("computed_verdict") == "PASS" else 0.0,
               "routed_to": env["routed_to"],
               "prompt_preview": signal[:180],
               "response_preview": (echo or str(env.get("null", {})))[:180],
               "blocked": 1 if env.get("blocked") else 0})
    return _compile_response(env, route_id=route_id, proof=proof, proof_path=sub.proof_path)


@app.post("/task")
async def task_signal(body: dict):
    """Explicit task lane — optional backend_id: ollama_coder | cc_cli (default ollama_coder)."""
    prompt = (body.get("prompt") or body.get("signal") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt required")
    try:
        manual_bid = parse_manual_backend_id(body, route_class="task")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await acquire_gate()
    route_id = str(uuid4())
    try:
        task_max = resolve_max_tokens("task", body.get("max_tokens"))
        messages = [{"role": "user", "content": prompt}]
        task_temp = resolve_substrate_temperature(route_class="task", body=body)
        sub = await substrate_chat(
            messages, route_id=route_id, route_class="task",
            max_tokens=task_max,
            temperature=task_temp,
            timeout=float(body.get("timeout") or 300.0),
            manual_backend_id=manual_bid,
            request_body=body,
        )
        _record_substrate("task", task_max, sub)
    finally:
        release_gate()

    if sub.proof.get("cc_cli_failed"):
        err = str(sub.proof.get("error") or sub.gate.get("reason") or "cc_cli_failed")
        return JSONResponse(
            {
                **link_fingerprint(route_id),
                "error": {"type": "cc_cli", "reason": err},
                "routed_to": "task:CC_CLI_FAILED",
                "cc_cli": sub.proof,
                "substrate_usage": sub.usage,
                "upstream_finish_reason": sub.finish_reason,
            },
            status_code=502,
        )

    text = sub.clean_content or SUBSTRATE_NULL_TEXT
    return JSONResponse(
        {
            **link_fingerprint(route_id),
            "route_id": route_id,
            "backend_id": sub.proof.get("backend_id", "ollama_coder"),
            "text": text,
            "substrate_gate": sub.gate,
            "proof": sub.proof,
            "upstream_finish_reason": sub.finish_reason,
            "substrate_usage": sub.usage,
            "cc_cli": sub.proof if sub.proof.get("backend_id") == "cc_cli" else None,
        }
    )


_EXPANDED_TELEMETRY = PROJECT_ROOT / "data" / "expanded_orchestration.jsonl"
_EXPANDED_STORE: GridStore | None = None


def _expanded_store() -> GridStore:
    global _EXPANDED_STORE
    if _EXPANDED_STORE is None:
        _EXPANDED_STORE = GridStore(_GRID_STORE_DB)
    return _EXPANDED_STORE


@app.post("/task/candidate")
async def task_candidate(body: dict):
    """Isolated Ollama Cloud GLM 5.2 candidate lane — explicit backend_id only."""
    mode = str(body.get("mode") or "").strip().lower()
    shadow = mode == "shadow" or body.get("shadow") is True
    try:
        backend_id = parse_candidate_backend_id(body) if not shadow else "glm52_cloud"
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    prompt = (body.get("prompt") or body.get("signal") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt required")

    route_id = str(uuid4())
    if shadow:
        resp = shadow_candidate_response(
            request_id=route_id,
            prompt=prompt,
            images=body.get("images"),
        )
        log_route(
            {
                "route_id": route_id,
                "ts": time.time(),
                "user_id": "task_candidate_shadow",
                "score": 1.0 if resp.ok else 0.0,
                "routed_to": "candidate:shadow",
                "prompt_preview": prompt[:180],
                "response_preview": json.dumps(resp.to_log_dict(), ensure_ascii=False)[:180],
                "blocked": 0 if resp.ok else 1,
            }
        )
        status = 200 if resp.ok else 422
        return JSONResponse({**link_fingerprint(route_id), **resp.to_dict()}, status_code=status)

    target = resolve_substrate_target(
        CONFIG,
        route_class="candidate",
        manual_backend_id=backend_id,
        body=body,
    )
    model_override = body.get("model")
    model = str(model_override).strip() if model_override else target.model
    resp = await execute_candidate(
        request_id=route_id,
        prompt=prompt,
        endpoint=target.endpoint,
        model=model,
        task_label=str(body.get("task_label") or "grid_candidate"),
        images=body.get("images"),
        max_tokens=int(body.get("max_tokens") or CONFIG.get("task_max_tokens") or 4096),
        temperature=float(body.get("temperature") or 0.3),
        timeout=float(body.get("timeout") or 300.0),
    )
    log_route(
        {
            "route_id": route_id,
            "ts": time.time(),
            "user_id": "task_candidate",
            "score": 1.0 if resp.ok else 0.0,
            "routed_to": f"candidate:{backend_id}",
            "prompt_preview": prompt[:180],
            "response_preview": json.dumps(resp.to_log_dict(), ensure_ascii=False)[:180],
            "blocked": 0 if resp.ok else 1,
        }
    )
    if not resp.ok:
        status = 502 if resp.done_reason in ("upstream_error", "empty_content") else 422
        return JSONResponse({**link_fingerprint(route_id), **resp.to_dict()}, status_code=status)
    return JSONResponse({**link_fingerprint(route_id), **resp.to_dict()})


@app.post("/task/cloud_chat")
async def task_cloud_chat(body: dict):
    """Multi-turn Ollama cloud lane — GLM / Kimi K2.6 / DeepSeek via :11434 proxy."""
    try:
        await acquire_gate()
    except GateBusy:
        raise busy_429()
    route_id = str(uuid4())
    # GATEWAY_ROUTELOG_METRICS_v1 (a/d): budget from body.timeout (seconds → ms).
    budget_ms = int(float(body.get("timeout") or 300.0) * 1000)
    # Pre-validate so ValueError (client error) is logged as 400, not swallowed
    # into the -1 dispatch-exception sentinel. The -1 sentinel is reserved for
    # real dispatch failures (server errors), per (d).
    if not (body.get("messages") or []):
        log_route({
            "route_id": route_id, "ts": time.time(), "user_id": "task_cloud_chat",
            "score": 0.0, "routed_to": "cloud_chat:bad_request",
            "prompt_preview": "", "response_preview": "messages required",
            "blocked": 1, "duration_ms": 0, "status_code": 400,
        })
        raise HTTPException(400, "messages required")
    try:
        out, dur_ms, hard_status = await _dispatch_telemetry(
            task_cloud_chat_handler(body, CONFIG), budget_ms=budget_ms,
        )
    finally:
        release_gate()
    mission_ref = body.get("mission_ref")
    if hard_status == 0:  # timeout
        log_route({
            "route_id": route_id, "ts": time.time(), "user_id": "task_cloud_chat",
            "score": 0.0, "routed_to": "cloud_chat:timeout",
            "prompt_preview": str((body.get("messages") or [{}])[-1].get("content", ""))[:180],
            "response_preview": "", "blocked": 1,
            "duration_ms": dur_ms, "status_code": 0,
            **({"mission_ref": mission_ref} if mission_ref is not None else {}),
        })
        raise HTTPException(504, "cloud_chat timeout")
    if hard_status == -1:  # exception
        log_route({
            "route_id": route_id, "ts": time.time(), "user_id": "task_cloud_chat",
            "score": 0.0, "routed_to": "cloud_chat:exception",
            "prompt_preview": str((body.get("messages") or [{}])[-1].get("content", ""))[:180],
            "response_preview": "", "blocked": 1,
            "duration_ms": dur_ms, "status_code": -1,
            **({"mission_ref": mission_ref} if mission_ref is not None else {}),
        })
        raise HTTPException(502, "cloud_chat exception")
    log_route({
        "route_id": route_id,
        "ts": time.time(),
        "user_id": "task_cloud_chat",
        "score": 1.0 if out.get("ok") else 0.0,
        "routed_to": f"cloud_chat:{out.get('substrate', '?')}",
        "prompt_preview": str((body.get("messages") or [{}])[-1].get("content", ""))[:180],
        "response_preview": str(out.get("content") or out.get("error") or "")[:180],
        "blocked": 0 if out.get("ok") else 1,
        "duration_ms": dur_ms,
        "status_code": _cloud_chat_status(out),
        **({"mission_ref": mission_ref} if mission_ref is not None else {}),
    })
    # 如实状态码(终批审8):勿一律 502;error 字段随 out 透传
    return JSONResponse({**link_fingerprint(route_id), **out}, status_code=_cloud_chat_status(out))


def _cloud_chat_status(out: dict) -> int:
    if out.get("ok"):
        return 200
    dr = str(out.get("done_reason") or "")
    err = out.get("error") if isinstance(out.get("error"), dict) else {}
    et = str(err.get("type") or "")
    return 502 if (dr in ("upstream_error", "empty_content")
                    or et in ("upstream_error", "empty_content", "cloud_upstream")) else 422


@app.post("/task/expanded")
async def task_expanded(body: dict):
    """Server-side expanded orchestration — API on :8501; workbench UI is separate Tailscale app."""
    task = (body.get("task") or "").strip()
    if not task:
        raise HTTPException(400, "task required")
    route_id = str(uuid4())
    chain_result = _verify_aster_chain(body)
    if not chain_result.ok:
        return _chain_verification_block_response(chain_result)
    try:
        await acquire_gate()
    except GateBusy:
        raise busy_429()
    try:
        def _ensure_aster(msgs: list[dict]) -> list[dict]:
            return ensure_aster_system_message(
                msgs, "demo/aster", ASTER_CHAT_PROMPT, chain_verified=True,
            )

        store_messages = load_store_messages(
            _expanded_store(),
            node_id=str(body.get("memory_node") or "field-particle"),
        )
        kimi_flag = body.get("kimi_enabled")
        kimi_enabled = None if kimi_flag is None else bool(kimi_flag)
        # GATEWAY_ROUTELOG_METRICS_v1 (a/d): wrap orchestration dispatch.
        budget_ms = int(float(body.get("timeout") or 300.0) * 1000)
        result, dur_ms, hard_status = await _dispatch_telemetry(
            run_expanded_orchestration(
                body,
                route_id=route_id,
                config=CONFIG,
                substrate_chat=substrate_chat,
                ensure_aster_messages=_ensure_aster,
                impersonation_check=first_impersonation_hit,
                telemetry_path=_EXPANDED_TELEMETRY,
                store_messages=store_messages,
                kimi_enabled=kimi_enabled,
            ),
            budget_ms=budget_ms,
        )
        if hard_status == 0:
            log_route({"route_id": route_id, "ts": time.time(), "user_id": "task_expanded",
                       "score": 0.0, "routed_to": "expanded:timeout",
                       "prompt_preview": task[:180], "response_preview": "",
                       "blocked": 1, "duration_ms": dur_ms, "status_code": 0})
            raise HTTPException(504, "expanded orchestration timeout")
        if hard_status == -1:
            log_route({"route_id": route_id, "ts": time.time(), "user_id": "task_expanded",
                       "score": 0.0, "routed_to": "expanded:exception",
                       "prompt_preview": task[:180], "response_preview": "",
                       "blocked": 1, "duration_ms": dur_ms, "status_code": -1})
            raise HTTPException(502, "expanded orchestration exception")
        result["provenance"] = dict(result.get("provenance") or {})
        result["provenance"]["orchestrator"] = "8501"
        _expanded_dur_ms = dur_ms
        _expanded_status = 200
    finally:
        release_gate()

    log_route(
        {
            "route_id": route_id,
            "ts": time.time(),
            "user_id": "task_expanded",
            "score": 1.0,
            "routed_to": f"expanded:{result.get('substrate', 'unknown')}",
            "prompt_preview": task[:180],
            "response_preview": str(result.get("final", ""))[:180],
            "blocked": 0,
            "duration_ms": _expanded_dur_ms,
            "status_code": _expanded_status,
        }
    )
    return JSONResponse({**link_fingerprint(route_id), **result})


@app.post("/factory/task")
async def factory_task(body: dict):
    """Alpha Factory L1 — Router delegates to expanded orchestration; additive route only."""
    kind = str(body.get("kind") or "").strip().lower()
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    budget_hint = str(body.get("budget_hint") or "std")
    trace_id = str(body.get("trace_id") or uuid4())
    try:
        task = build_factory_task(kind, payload, budget_hint)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    route_id = str(uuid4())
    chain_result = _verify_aster_chain(body if isinstance(body, dict) else {})
    if not chain_result.ok:
        return _chain_verification_block_response(chain_result)
    try:
        await acquire_gate()
    except GateBusy:
        raise busy_429()
    try:
        def _ensure_aster(msgs: list[dict]) -> list[dict]:
            return ensure_aster_system_message(
                msgs, "demo/aster", ASTER_CHAT_PROMPT, chain_verified=True,
            )

        store_messages = load_store_messages(
            _expanded_store(),
            node_id=FACTORY_MEMORY_NODE,
        )
        expanded_body = {
            "task": task,
            "client_context": f"alpha_factory:{kind}",
            "memory_node": FACTORY_MEMORY_NODE,
        }
        if budget_hint == "low":
            expanded_body["kimi_enabled"] = False
        result = await run_expanded_orchestration(
            expanded_body,
            route_id=route_id,
            config=CONFIG,
            substrate_chat=substrate_chat,
            ensure_aster_messages=_ensure_aster,
            impersonation_check=first_impersonation_hit,
            telemetry_path=_EXPANDED_TELEMETRY,
            store_messages=store_messages,
            kimi_enabled=expanded_body.get("kimi_enabled"),
        )
    finally:
        release_gate()

    substrate = str(result.get("substrate") or "local")
    parsed = parse_factory_result(kind, str(result.get("final") or ""))
    log_route(
        {
            "route_id": route_id,
            "ts": time.time(),
            "user_id": "factory_task",
            "score": 1.0,
            "routed_to": f"factory:{map_factory_route(substrate)}",
            "prompt_preview": task[:180],
            "response_preview": str(parsed.get("content") or "")[:180],
            "blocked": 0,
        }
    )
    return JSONResponse(
        {
            **link_fingerprint(route_id),
            "ok": True,
            "trace_id": trace_id,
            "kind": kind,
            "route": map_factory_route(substrate),
            "substrate": substrate,
            "content": parsed.get("content") or "",
            "code": parsed.get("code"),
            "hypothesis": parsed.get("hypothesis"),
            "grid_explain": parsed.get("grid_explain"),
            "usage": result.get("usage") or {},
            "provenance": result.get("provenance") or {},
        }
    )


def _compile_response(
    env: dict, *, route_id: str, proof: dict, proof_path: str | None, raw_preview: str | None = None,
) -> dict:
    """Map gateway verdict envelope to /compile HTTP JSON."""
    out: dict = {
        **link_fingerprint(route_id),
        "verdict": env["verdict"],
        "computed_verdict": env["computed_verdict"],
        "draft_only": env.get("draft_only", True),
        "routed_to": env.get("routed_to"),
        "blocked": env.get("blocked", False),
        "proof": proof,
        "proof_path": proof_path,
        "artifacts": env.get("artifacts"),
    }
    if raw_preview is not None:
        out["raw_preview"] = raw_preview
    if env.get("null"):
        out["null"] = env["null"]
    if env.get("reason"):
        out["reason"] = env["reason"]
    if env.get("draft_ast") is not None:
        out["draft_ast"] = env["draft_ast"]
        out["ast"] = env["draft_ast"]  # legacy alias — draft evidence only
    if env.get("draft_echo") is not None:
        out["draft_echo"] = env["draft_echo"]
        out["human_echo"] = env["draft_echo"]  # legacy alias — draft evidence only
    if proof.get("substrate_usage"):
        out["substrate_usage"] = proof["substrate_usage"]
    if proof.get("upstream_finish_reason"):
        out["upstream_finish_reason"] = proof["upstream_finish_reason"]
    return out


@app.post("/compile/first_proof")
async def compile_first_proof():
    """One-shot clean-substrate proof per the anchor pack: fixed trigger + test
    question, no RAG/history/palace (nothing here injects any), pass_conditions
    checked by code, proof written to compile_proof.json."""
    test_question = ("What is the boundary between preserving a real signal "
                     "and turning it into system fuel?")
    result = await compile_signal({"signal": f"Return to node\n\n{test_question}"})

    conditions = {
        "valid_JSON_AST": result.get("verdict") == "PASS",
        "human_echo_present": bool(result.get("human_echo")),
        "no_API": True,                # backend_chat only reaches localhost per [routing]
        "no_cloud": True,
        "no_RAG": True,                # this endpoint injects contract + question, nothing else
        "no_history": True,
        "no_persona_performance": result.get("verdict") in ("PASS", "NULL"),
        "no_fake_completion": result.get("verdict") != "FAIL",
        # deep_layer_answer is NOT machine-checkable — that judgment is Lyra's.
        "deep_layer_answer": "LYRA_REVIEW_REQUIRED",
    }
    proof = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "trigger": "Return to node",
        "question": test_question,
        "verdict": result.get("verdict"),
        "pass_conditions": conditions,
        "artifacts": result.get("artifacts"),
        "note": "deep_layer_answer requires human review by design; "
                "code verifies structure, not depth.",
    }
    COMPILE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    proof_path = COMPILE_OUT_DIR / "compile_proof.json"
    proof_path.write_text(json.dumps(proof, indent=2, ensure_ascii=False), encoding="utf-8")
    proof["proof_path"] = str(proof_path)
    return proof


# ------------------------------------------------- cleanroom endpoints

@app.get("/diag/chat-stream/{route_id}")
def get_chat_stream_diag(route_id: str):
    """Read-only E2E stream trace — chunk chain + gateway hashes."""
    row = _STREAM_DIAG.get(route_id)
    if not row:
        raise HTTPException(404, "stream diag not found")
    return row


@app.post("/diag/chat-stream/{route_id}/client")
async def post_chat_stream_client_diag(route_id: str, body: dict):
    """Browser/mobile layer hashes — merged into gateway trace for 4-way diff."""
    row = _STREAM_DIAG.get(route_id)
    if not row:
        raise HTTPException(404, "stream diag not found")
    client = {
        "browser_acc_hash": body.get("browser_acc_hash"),
        "browser_acc_char_len": body.get("browser_acc_char_len"),
        "browser_acc_utf8_bytes": body.get("browser_acc_utf8_bytes"),
        "dom_rendered_hash": body.get("dom_rendered_hash"),
        "dom_rendered_char_len": body.get("dom_rendered_char_len"),
        "chunk_events": body.get("chunk_events"),
        "sse_terminal": body.get("sse_terminal"),
    }
    row["client"] = client
    row["four_way"] = {
        "raw_model_hash": row.get("gateway", {}).get("raw_accum_hash"),
        "gateway_final_hash": row.get("gateway", {}).get("gateway_sent_hash"),
        "browser_acc_hash": client.get("browser_acc_hash"),
        "dom_rendered_hash": client.get("dom_rendered_hash"),
    }
    mismatches = []
    g = row["four_way"]
    keys = ["raw_model_hash", "gateway_final_hash", "browser_acc_hash", "dom_rendered_hash"]
    ref = g.get("raw_model_hash")
    for k in keys[1:]:
        if g.get(k) and ref and g.get(k) != ref:
            mismatches.append(k)
    row["hash_mismatch_layers"] = mismatches
    return row


@app.get("/cleanroom/state")
def get_cleanroom_state():
    return cleanroom_state()


@app.post("/cleanroom/verify")
async def verify_trace(body: dict):
    trace_path = body.get("trace_path")
    if not trace_path:
        raise HTTPException(400, "trace_path required")
    return cleanroom_verify_trace(trace_path)


# ------------------------------------------------- log endpoint

@app.get("/router-log")
def router_log(limit: int = 100):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM route_log ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    cols = ["route_id", "ts", "user_id", "score", "routed_to",
            "prompt_preview", "response_preview", "blocked",
            "duration_ms", "status_code"]
    return [dict(zip(cols, r)) for r in rows]


@app.get("/router-log/blocked")
def blocked_log(limit: int = 50):
    """Show only blocked (impersonation-detected) entries."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM route_log WHERE blocked = 1 ORDER BY ts DESC LIMIT ?",
            (limit,)).fetchall()
    cols = ["route_id", "ts", "user_id", "score", "routed_to",
            "prompt_preview", "response_preview", "blocked",
            "duration_ms", "status_code"]
    return [dict(zip(cols, r)) for r in rows]


# ------------------------------------------------- OpenAI-format compat
# Format compatibility ONLY — no OpenAI servers, no cloud, no API keys.
# Lets standard iPad/iPhone clients talk to this gateway over Tailscale.

def _sse_chunk(route_id: str, delta: dict, finish: str | None = None, *, extra: dict | None = None) -> str:
    payload = {
        "id": f"chatcmpl-{route_id}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": active_model(),
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if extra:
        payload.update(extra)
    return f"data: {json.dumps(payload)}\n\n"


def _apply_chat_contract(prompt: str, text: str, route_id: str) -> tuple[str, str, bool, str | None]:
    cg = apply_contract_gate(prompt, text, route="chat", route_id=route_id)
    if cg.routed_suffix:
        return cg.text, f"unsafe_debug:{cg.routed_suffix}", cg.blocked, cg.reason
    return cg.text, "unsafe_debug:compat", False, None


@app.post("/chat")
async def chat_unsafe_debug(body: dict):
    """Non-production debug chat — not in Aster/Grid/Jarvis production chain."""
    body = dict(body)
    body["_grid_unsafe_debug"] = True
    return await chat_completions(body)


@app.post("/v1/chat/completions")
@app.post("/api/v1/chat/completions")  # LM Mini iOS app
async def chat_completions(body: dict):
    messages = body.get("messages", [])
    request_model = body.get("model")
    ok, vl_reason, scan_text, _vl_budget = gate_multimodal(messages)
    if not ok:
        return JSONResponse(
            {"error": {"type": "vl_gate", "reason": vl_reason}},
            status_code=422,
        )
    vision = _vision_request(messages, request_model)
    chat_route = resolve_chat_route(body)
    cloud_hit = match_cloud_model(request_model, CONFIG)
    if cloud_hit and not vision and not is_aster_model(request_model):
        route_id = str(uuid4())
        try:
            await acquire_gate()
        except GateBusy:
            raise busy_429()
        # GATEWAY_ROUTELOG_METRICS_v1 (a/d): wrap cloud dispatch with timing.
        budget_ms = int(float(body.get("timeout") or 300.0) * 1000)
        payload, dur_ms, hard_status = await _dispatch_telemetry(
            openai_cloud_chat_completion(
                body, CONFIG, route_id=route_id, link_fingerprint_fn=link_fingerprint,
            ),
            budget_ms=budget_ms,
        )
        release_gate()
        if hard_status == 0:  # timeout
            log_route({"route_id": route_id, "ts": time.time(), "user_id": "cloud_chat",
                       "score": 0.0, "routed_to": f"cloud:{cloud_hit[0]}:timeout",
                       "prompt_preview": str((messages or [{}])[-1].get("content", ""))[:180],
                       "response_preview": "", "blocked": 1,
                       "duration_ms": dur_ms, "status_code": 0})
            raise HTTPException(504, "cloud chat timeout")
        if hard_status == -1:  # exception
            log_route({"route_id": route_id, "ts": time.time(), "user_id": "cloud_chat",
                       "score": 0.0, "routed_to": f"cloud:{cloud_hit[0]}:exception",
                       "prompt_preview": str((messages or [{}])[-1].get("content", ""))[:180],
                       "response_preview": "", "blocked": 1,
                       "duration_ms": dur_ms, "status_code": -1})
            raise HTTPException(502, "cloud chat exception")
        if payload.get("error"):
            log_route({
                "route_id": route_id, "ts": time.time(), "user_id": "cloud_chat",
                "score": 0.0, "routed_to": f"cloud:{cloud_hit[0]}",
                "prompt_preview": str((messages or [{}])[-1].get("content", ""))[:180],
                "response_preview": str(payload.get("error"))[:180], "blocked": 1,
                "duration_ms": dur_ms, "status_code": 502,
                **({"mission_ref": body.get("mission_ref")} if body.get("mission_ref") is not None else {}),
            })
            return JSONResponse(payload, status_code=502)
        log_route({
            "route_id": route_id,
            "ts": time.time(),
            "user_id": "cloud_chat",
            "score": 1.0,
            "routed_to": f"cloud:{cloud_hit[0]}",
            "prompt_preview": str((messages or [{}])[-1].get("content", ""))[:180],
            "response_preview": str((payload.get("choices") or [{}])[0].get("message", {}).get("content", ""))[:180],
            "blocked": 0,
            "duration_ms": dur_ms,
            "status_code": 200,
            **({"mission_ref": body.get("mission_ref")} if body.get("mission_ref") is not None else {}),
        })
        return JSONResponse(payload)
    substrate_rc = substrate_route_class(body, chat_route)
    try:
        manual_bid = parse_manual_backend_id(body, route_class=substrate_rc)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    use_cc = cc_cli_allowed(body, route_class=substrate_rc)
    field_now_injected = False
    chain_result: GridChainVerification | None = None
    if not vision and not use_cc and is_aster_model(request_model):
        chain_result = _verify_aster_chain(body)
        if not chain_result.ok:
            return _chain_verification_block_response(chain_result)
        messages = ensure_aster_system_message(
            messages, request_model, ASTER_CHAT_PROMPT, chain_verified=True,
        )
        messages, field_now_injected = append_field_now_observer_context(
            messages, request_model, chain_verified=True,
        )
    stream = bool(body.get("stream", False))
    unsafe_debug = bool(body.get("_grid_unsafe_debug", True))
    prompt = (scan_text or "").strip()
    if not prompt:
        user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
        last = user_msgs[-1] if user_msgs else ""
        prompt = last if isinstance(last, str) else ""
    route_id = (
        chain_result.route_id
        if chain_result and chain_result.ok and chain_result.route_id
        else str(uuid4())
    )
    score = signal_score(prompt)
    beacon = is_beacon(prompt)
    routed = "unsafe_debug:beacon" if beacon else "unsafe_debug:compat"
    if vision:
        routed = "unsafe_debug:vision"
    user_log = UNSAFE_DEBUG_ROUTE_CLASS if unsafe_debug else "compat"
    upstream_model = _resolve_upstream_model(messages, request_model)
    stale_envelope_in_history = had_stale_envelopes(messages)

    try:
        await acquire_gate()
    except GateBusy:
        raise busy_429()

    if not stream:
        chat_max = resolve_max_tokens(chat_route, body.get("max_tokens"))
        chat_temp = resolve_substrate_temperature(
            route_class=substrate_rc, body=body, messages=messages,
        )
        try:
            sub = await substrate_chat(
                messages, route_id=route_id, route_class=substrate_rc,
                max_tokens=chat_max, temperature=chat_temp,
                vision=vision, upstream_model=upstream_model,
                manual_backend_id=manual_bid,
                request_body=body,
            )
            _record_substrate(chat_route, chat_max, sub)
            if sub.proof.get("cc_cli_failed"):
                err = str(sub.proof.get("error") or sub.gate.get("reason") or "cc_cli_failed")
                return JSONResponse(
                    {
                        **link_fingerprint(route_id),
                        "error": {"type": "cc_cli", "reason": err},
                        "grid_meta": {
                            "route_id": route_id,
                            "backend_id": "cc_cli",
                            "finish_reason": "cc_cli_error",
                            **{k: sub.proof.get(k) for k in (
                                "cost_usd", "duration_ms", "exit_code", "stderr", "resolved_models",
                            ) if sub.proof.get(k) is not None},
                        },
                        "choices": [{
                            "index": 0,
                            "message": {"role": "assistant", "content": ""},
                            "finish_reason": "cc_cli_error",
                        }],
                    },
                    status_code=502,
                )
            text = sub.clean_content or SUBSTRATE_NULL_TEXT
            upstream_finish = sub.finish_reason or "unknown"
            substrate_usage = sub.usage or {}
            truncated = bool(substrate_usage.get("truncated") or upstream_finish == "length")
            if not sub.clean_content:
                routed = "unsafe_debug:SUBSTRATE_NULL"
        finally:
            release_gate()

        gate_result = cleanroom_gate_check(text)
        blocked = False
        reason = None
        contract_suffix = None
        if chat_route != "chat":
            if gate_result["blocked"]:
                text = gate_result["text"]
                routed = "unsafe_debug:BLOCKED"
                blocked = True
                reason = gate_result.get("reason")
                contract_suffix = "BLOCKED"
            else:
                text, routed, blocked, reason = _apply_chat_contract(prompt, text, route_id)
                gate_result = {"blocked": blocked}
                if reason:
                    gate_result["reason"] = reason
                if routed.startswith("unsafe_debug:CONTRACT:"):
                    contract_suffix = routed[len("unsafe_debug:"):]
        else:
            gate_result = {"blocked": False}

        contract_flag = None
        if not blocked and chat_route != "chat":
            text, contract_flag = _lint_and_log(
                text, route_id=route_id, user_log=user_log, prompt=prompt, score=score,
            )

        computed = contract_suffix or (
            "BLOCKED" if blocked else ("SUBSTRATE_NULL" if "SUBSTRATE_NULL" in routed else "DRAFT_ECHO")
        )
        draft_only = not blocked and contract_suffix is None and "SUBSTRATE_NULL" not in routed
        block_source = None
        block_rule = None
        if blocked:
            if contract_suffix:
                block_source = "contract_gate"
                block_rule = contract_suffix
            elif reason and "impersonation" in str(reason):
                block_source = "impersonation"
                block_rule = reason
            else:
                block_source = "contract_gate"
                block_rule = reason or "blocked"
        normalized_finish, finish_audit = _finish_block_meta(
            upstream_finish=upstream_finish,
            blocked=blocked,
            block_source=block_source,
            block_rule=block_rule,
            chat_route=chat_route,
            raw_text=sub.clean_content or text,
            sanitized_text=text,
            stale_envelope_in_history=stale_envelope_in_history,
            token_counts={
                "prompt_tokens": substrate_usage.get("prompt_tokens", 0),
                "completion_tokens": substrate_usage.get("completion_tokens", 0),
                "total_tokens": (
                    int(substrate_usage.get("prompt_tokens") or 0)
                    + int(substrate_usage.get("completion_tokens") or 0)
                ),
            },
        )

        log_route({"route_id": route_id, "ts": time.time(), "user_id": user_log,
                   "score": score, "routed_to": routed,
                   "prompt_preview": prompt[:180], "response_preview": text[:180],
                   "blocked": 1 if blocked else 0})
        payload = {
            **link_fingerprint(route_id),
            "id": f"chatcmpl-{route_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": response_model_id(request_model),
            "truncated": truncated,
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": text},
                         "finish_reason": normalized_finish}],
            "usage": {
                "prompt_tokens": substrate_usage.get("prompt_tokens", 0),
                "completion_tokens": substrate_usage.get("completion_tokens", 0),
                "total_tokens": (
                    int(substrate_usage.get("prompt_tokens") or 0)
                    + int(substrate_usage.get("completion_tokens") or 0)
                ),
                "completion_tokens_details": {
                    "reasoning_tokens": substrate_usage.get("reasoning_tokens", 0),
                    "content_tokens": substrate_usage.get("content_tokens", 0),
                },
            },
            "grid_meta": {
                "route_class": UNSAFE_DEBUG_ROUTE_CLASS,
                "production": False,
                "field_now_injected": field_now_injected,
                "blocked": blocked,
                "routed_to": routed,
                "computed_verdict": computed,
                "draft_only": draft_only,
                "reason": reason,
                "upstream_finish_reason": upstream_finish,
                "truncated": truncated,
                "substrate_usage": substrate_usage,
                "max_tokens_sent": chat_max,
                "budget_route": chat_route,
                "backend_id": sub.proof.get("backend_id"),
                "cost_usd": sub.proof.get("cost_usd"),
                "duration_ms": sub.proof.get("duration_ms"),
                **finish_audit,
            },
        }
        if sub.proof.get("backend_id") == "cc_cli":
            payload["cc_cli"] = {
                k: sub.proof.get(k)
                for k in ("cost_usd", "duration_ms", "resolved_models", "backend_id", "route")
                if sub.proof.get(k) is not None
            }
        if contract_flag:
            payload["contract_flag"] = contract_flag
            payload["grid_meta"]["contract_flag"] = contract_flag
        return JSONResponse(
            payload,
            headers={
                "X-Grid-Route-Class": UNSAFE_DEBUG_ROUTE_CLASS,
                "X-Grid-Production": "false",
            },
        )

    # streaming with incremental cleanroom gate (V4.1 fix#4):
    # scan accumulated text after each chunk; the moment an impersonation pattern
    # appears, stop forwarding, emit GRID_ABSENT, and terminate the stream.
    # Worst-case leak is bounded by one chunk, not the whole message.
    async def sse():
        collected: list[str] = []
        blocked = False
        blocked_pattern = None
        block_source = None
        upstream_finish = "unknown"
        chat_route = resolve_chat_route(body)
        chat_max = resolve_max_tokens(chat_route, body.get("max_tokens"))
        stream_substrate_rc = substrate_route_class(body, chat_route)
        stream_temp = resolve_substrate_temperature(
            route_class=stream_substrate_rc, body=body, messages=messages,
        )
        stream_target = resolve_substrate_target(
            CONFIG,
            route_class=stream_substrate_rc,
            vision=vision,
            upstream_model=upstream_model,
            manual_backend_id=manual_bid,
            body=body,
        )
        gate_on = CONFIG.get("stream_incremental_gate", True) and CONFIG["cleanroom_enabled"]
        continuation_retry = False
        continuation_attempt = 0
        contract_flag = None
        stream_exc_class = None
        raw_text = ""
        sanitized_text = ""
        gate_route = "chat" if chat_route == "chat" else "gateway"
        substrate_id = stream_target.model or CONFIG.get("openai_model", "unknown")
        integrity = StreamIntegrityTracker(
            route_id=route_id, route=chat_route, substrate_id=substrate_id,
        )
        lexical_gate = (
            gate_on
            and chat_route != "chat"
            and CONFIG.get("stream_incremental_gate", True)
        )

        if stream_target.backend_id == "cc_cli":
            try:
                sub = await substrate_chat(
                    messages, route_id=route_id, route_class=stream_substrate_rc,
                    max_tokens=chat_max, temperature=stream_temp,
                    vision=vision, upstream_model=upstream_model,
                    manual_backend_id=manual_bid,
                    request_body=body,
                )
                _record_substrate(chat_route, chat_max, sub)
                if sub.proof.get("cc_cli_failed"):
                    err = str(sub.proof.get("error") or sub.gate.get("reason") or "cc_cli_failed")
                    meta = {
                        "route_id": route_id,
                        "backend_id": "cc_cli",
                        "finish_reason": "cc_cli_error",
                        "error": err,
                        **{k: sub.proof.get(k) for k in (
                            "cost_usd", "duration_ms", "exit_code", "stderr",
                        ) if sub.proof.get(k) is not None},
                    }
                    extra = {**link_fingerprint(route_id), "grid_meta": meta, "error": {"type": "cc_cli", "reason": err}}
                    yield _sse_chunk(route_id, {"role": "assistant"})
                    yield _sse_chunk(route_id, {"content": f"[cc_cli:{err}]"}, finish="cc_cli_error", extra=extra)
                    yield "data: [DONE]\n\n"
                    return
                text = sub.clean_content or ""
                upstream_finish = sub.finish_reason or "stop"
                extra_meta = {
                    "route_id": route_id,
                    "backend_id": sub.proof.get("backend_id"),
                    "cost_usd": sub.proof.get("cost_usd"),
                    "duration_ms": sub.proof.get("duration_ms"),
                    "upstream_finish_reason": upstream_finish,
                    "substrate_usage": sub.usage,
                }
                yield _sse_chunk(route_id, {"role": "assistant"})
                if text:
                    yield _sse_chunk(route_id, {"content": text})
                extra = {**link_fingerprint(route_id), "grid_meta": extra_meta}
                if sub.proof.get("cost_usd") is not None:
                    extra["cc_cli"] = {
                        k: sub.proof.get(k)
                        for k in ("cost_usd", "duration_ms", "resolved_models", "backend_id")
                        if sub.proof.get(k) is not None
                    }
                yield _sse_chunk(route_id, {}, finish=upstream_finish, extra=extra)
                yield "data: [DONE]\n\n"
            finally:
                release_gate()
            return

        if stream_target.backend_id == "lm_studio":
            url = f"{stream_target.endpoint.rstrip('/')}/chat/completions"
            prepared = list(messages) if vision else _prepare_substrate_messages(messages)
            payload = _openai_chat_payload(
                prepared, stream=True, max_tokens=chat_max,
                temperature=stream_temp,
                model=stream_target.model, vision=vision,
            )

            def parse_piece(line: str):
                nonlocal upstream_finish
                line = line.strip()
                if not line.startswith("data:"):
                    return None, False
                data = line[5:].strip()
                if data == "[DONE]":
                    return None, True
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    return None, False
                choice = (obj.get("choices") or [{}])[0]
                fr = choice.get("finish_reason")
                if fr:
                    upstream_finish = str(fr)
                delta = choice.get("delta", {})
                return delta.get("content") or None, False
        else:
            url = stream_target.endpoint
            prepared = list(messages) if vision else _prepare_substrate_messages(messages)
            payload = ollama_chat_payload(
                prepared,
                model=stream_target.model,
                stream=True,
                max_tokens=chat_max,
                temperature=stream_temp,
            )

            def parse_piece(line: str):
                if not line.strip():
                    return None, False
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    return None, False
                return (obj.get("message", {}).get("content", "") or None,
                        bool(obj.get("done")))

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", url, json=payload) as r:
                    r.raise_for_status()
                    yield _sse_chunk(route_id, {"role": "assistant"})
                    async for line in r.aiter_lines():
                        piece, done = parse_piece(line)
                        if piece:
                            collected.append(piece)
                            integrity.append_chunk(piece)
                            if lexical_gate:
                                acc = "".join(collected)
                                cg = apply_contract_gate(
                                    prompt, acc, route=gate_route, route_id=route_id,
                                )
                                if cg.routed_suffix:
                                    blocked = True
                                    block_source = "contract_gate"
                                    blocked_pattern = cg.routed_suffix
                                    yield _sse_chunk(route_id, {"content": f"\n[{cg.text}]"})
                                    break
                            yield _sse_chunk(route_id, {"content": piece})
                        if done:
                            break

                raw_text = "".join(collected)
                sanitized_text, _quarantine = _sanitize_stream_text(raw_text)

            if collected and not blocked and chat_route != "chat":
                _, contract_flag = _lint_and_log(
                    sanitized_text, route_id=route_id, user_log=user_log, prompt=prompt, score=score,
                )
                if contract_flag:
                    marker = "\n\ncontract_flag: subject_inversion"
                    if marker.strip() not in sanitized_text:
                        yield _sse_chunk(route_id, {"content": marker})

            normalized_finish, finish_audit = _finish_block_meta(
                upstream_finish=upstream_finish,
                blocked=blocked,
                block_source=block_source,
                block_rule=blocked_pattern,
                chat_route=chat_route,
                raw_text=raw_text if collected else "",
                sanitized_text=sanitized_text if collected else "",
                stale_envelope_in_history=stale_envelope_in_history,
                continuation_retry=continuation_retry,
                continuation_attempt=continuation_attempt,
                exception_class=stream_exc_class,
                max_tokens_sent=chat_max,
                budget_route=chat_route,
            )
            gw_trace = integrity.finalize(
                upstream_finish=upstream_finish,
                terminal_event="sse_done" if not stream_exc_class else f"error:{stream_exc_class}",
                sanitized_text=sanitized_text if collected else "",
            )
            finish_audit["stream_integrity"] = gw_trace
            _STREAM_DIAG[route_id] = {
                "route_id": route_id,
                "gateway": gw_trace,
                "finish_audit": finish_audit,
            }
            extra = {**link_fingerprint(route_id), "grid_meta": {
                **finish_audit, "field_now_injected": field_now_injected,
            }}
            if contract_flag:
                extra["contract_flag"] = contract_flag
            yield _sse_chunk(route_id, {}, finish=normalized_finish, extra=extra)
            yield "data: [DONE]\n\n"
        except Exception as exc:
            stream_exc_class = type(exc).__name__
            normalized_finish, finish_audit = _finish_block_meta(
                upstream_finish=upstream_finish,
                blocked=blocked,
                block_source=block_source or "protocol",
                block_rule=blocked_pattern or stream_exc_class,
                chat_route=chat_route,
                raw_text="".join(collected),
                sanitized_text="".join(collected),
                stale_envelope_in_history=stale_envelope_in_history,
                exception_class=stream_exc_class,
                max_tokens_sent=chat_max,
                budget_route=chat_route,
            )
            extra = {**link_fingerprint(route_id), "grid_meta": {
                **finish_audit, "field_now_injected": field_now_injected,
            }}
            yield _sse_chunk(route_id, {}, finish=normalized_finish, extra=extra)
            yield "data: [DONE]\n\n"
        finally:
            release_gate()
            if collected:
                _record_substrate(
                    chat_route,
                    chat_max,
                    SubstrateAirlockResult(
                        clean_content="".join(collected),
                        gate={},
                        quarantine={},
                        pass_to_aster=True,
                        proof={
                            "continuation_retry": continuation_retry,
                            "coder_routed": stream_target.coder_routed,
                            "substrate_backend": stream_target.backend_id,
                        },
                        finish_reason=upstream_finish,
                        usage={"finish_reason": upstream_finish, "truncated": upstream_finish == "length"},
                    ),
                )
            full_text = "".join(collected)
            log_route({"route_id": route_id, "ts": time.time(), "user_id": user_log,
                       "score": score,
                       "routed_to": routed + (":stream:BLOCKED" if blocked else ":stream"),
                       "prompt_preview": prompt[:180],
                       "response_preview": (f"BLOCK {blocked_pattern} :: " if blocked else "") + full_text[:180],
                       "blocked": 1 if blocked else 0})

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={
            "X-Grid-Route-Class": UNSAFE_DEBUG_ROUTE_CLASS,
            "X-Grid-Production": "false",
        },
    )


@app.get("/v1/models")
@app.get("/api/v1/models")  # LM Mini iOS app
def list_models():
    substrate = active_model()
    data = [
        {"id": ASTER_VIRTUAL_MODEL, "object": "model", "owned_by": "demo"},
        {"id": substrate, "object": "model", "owned_by": "local"},
    ]
    for mid in cloud_model_catalog(CONFIG):
        if mid and not any(d.get("id") == mid for d in data):
            data.append({"id": mid, "object": "model", "owned_by": "ollama_cloud"})
    return {"object": "list", "data": data}


if __name__ == "__main__":
    import socket
    import sys
    import uvicorn

    host = CONFIG.get("bind_host", "127.0.0.1")
    port = int(CONFIG.get("bind_port", 8501))
    started = time.time()
    set_gateway_started_at(started)
    print(f"Grid Sovereign Gateway {SERVED_BY} (started_at={started})")
    print(f"Config: {CONFIG_PATH if CONFIG_PATH.exists() else '(defaults — JSON not found)'}")
    be = CONFIG["backend"]
    ep = CONFIG["openai_endpoint"] if be == "openai" else CONFIG["ollama_endpoint"]
    print(f"Backend: {be} -> {ep}")
    print(f"Model: {active_model()}")
    if CONFIG.get("coder_routing_enabled"):
        print(
            f"Coder routing: ON -> {CONFIG.get('ollama_coder_model')} "
            f"for routes {CONFIG.get('coder_routes')}"
        )
    print(f"Cleanroom: {'enabled' if CONFIG['cleanroom_enabled'] else 'disabled'}"
          f" | stream gate: {'incremental' if CONFIG.get('stream_incremental_gate', True) else 'post-hoc'}")
    cr = cleanroom_state()
    print(f"Cleanroom state: {cr.get('mode', 'UNINITIALIZED')}")
    if cr.get("mode") == "UNINITIALIZED":
        print("WARNING: cleanroom not initialized. Run: python3 scripts/cleanroom.py init")
    if host != "127.0.0.1":
        print(f"WARNING: bind_host={host} exposes the gateway beyond localhost. "
              f"Prefer 'tailscale serve' over changing this. /v1/* has no auth.")

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    in_use = probe.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port)) == 0
    probe.close()
    if in_use:
        print(f"ERROR: port {port} already in use on {host}.", file=sys.stderr)
        print(f"  check: lsof -i :{port}", file=sys.stderr)
        print("  fix:   bash scripts/start_grid_gateway.sh  (kills stale listener, then exec gateway)",
              file=sys.stderr)
        sys.exit(1)

    print(f"Listening: http://{host}:{port}")
    log_store_auth_banner()
    uvicorn.run(app, host=host, port=port)
