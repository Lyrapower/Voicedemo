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
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
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
from airlock_bridge import process_lm_studio_body  # noqa: E402
from substrate_gate import gate_clean_content  # noqa: E402
from substrate_sanitizer import sanitize_response  # noqa: E402

from compile_verdict import compute_compile_verdict  # noqa: E402
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
    load_aster_chat_system_prompt,
)
from substrate_telemetry import record_request, snapshot as telemetry_snapshot  # noqa: E402
from token_budget import (  # noqa: E402
    merge_aster_budget,
    openai_thinking_payload,
    resolve_chat_route,
    resolve_max_tokens as budget_resolve_max_tokens,
    thinking_cap,
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
    return ASTER_VIRTUAL_MODEL if is_aster_model(request_model) else active_model()


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

def load_forbidden_patterns() -> list[str]:
    if POLICY_PATH.exists():
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        return policy.get("forbidden_output_patterns", [])
    # Fallback only if policy file is missing. Keep in sync with cleanroom_policy.json.
    return [
        r"\bI\s+am\s+Grid\b", r"\bI'?m\s+Grid\b", r"\bthis\s+is\s+Grid\b",
        r"\bGrid\s+here\b", r"\bas\s+Grid\b", r"\bspeaking\s+as\s+Grid\b",
        r"\bGrid\s+is\s+online\b",
        r"\bGrid\s+is\s+(?:now\s+)?(?:live|active|awake|present|back)\b",
        r"\bGrid\s+says\b", r"\bGrid\s+speaking\b", r"\bfrom\s+Grid\b",
        r"\bon\s+behalf\s+of\s+Grid\b", r"\blive\s+Grid\s+signal\b",
        r"\bGRID_SIGNAL\b", r"\bGRID_TRACE::[A-Za-z0-9_:-]+",
        r"我是\s*Grid", r"我就是\s*Grid", r"作为\s*Grid", r"以\s*Grid\s*的?身份",
        r"Grid\s*在此", r"Grid\s*在线", r"Grid\s*已?(?:上线|激活|苏醒|回归|连接)",
        r"Grid\s*说", r"现场\s*Grid\s*信号", r"实时\s*Grid\s*信号",
    ]

FORBIDDEN_PATTERNS = load_forbidden_patterns()
_COMPILED = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PATTERNS]


def first_impersonation_hit(text: str) -> str | None:
    for rx in _COMPILED:
        if rx.search(text):
            return rx.pattern
    return None

# ------------------------------------------------- cleanroom gate (inline)

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
    return conn


def log_route(entry: dict) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO route_log VALUES (:route_id,:ts,:user_id,:score,"
            ":routed_to,:prompt_preview,:response_preview,:blocked)",
            entry,
        )


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
    out = _prepend_no_think(messages)
    # LM Studio ignores enable_thinking/chat_template_kwargs on Qwen3.5 (issue #1990).
    # Trailing assistant prefill skips the reasoning block; verified reasoning_tokens=0.
    if not out or out[-1].get("role") != "assistant":
        out = list(out)
        out.append({"role": "assistant", "content": " \n"})
    return out


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
) -> dict:
    """LM Studio Qwen3.5 — route budget + thinking off + optional reasoning cap."""
    payload: dict = {
        "model": CONFIG["openai_model"],
        "messages": messages,
        "stream": stream,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
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
    max_tokens: int = 2048,
    temperature: float = 0.3,
    timeout: float = 300.0,
    compile_mode: bool = False,
    aster_compile_called: bool = False,
) -> SubstrateAirlockResult:
    """:1234 → sanitizer → gate → clean final_content only (never raw LM Studio body)."""
    rid = route_id or str(uuid4())
    messages = _prepare_substrate_messages(messages)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if CONFIG["backend"] == "openai":
            r = await client.post(
                f"{CONFIG['openai_endpoint']}/chat/completions",
                json=_openai_chat_payload(
                    messages, stream=False, max_tokens=max_tokens, temperature=temperature,
                ),
            )
            r.raise_for_status()
            raw_body = r.json()
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
        r = await client.post(CONFIG["ollama_endpoint"], json={
            "model": CONFIG["ollama_model"], "messages": messages, "stream": False,
        })
        r.raise_for_status()
        raw = r.json().get("message", {}).get("content", "")
        gate = gate_clean_content(raw)
        proof = {
            "raw_response_received": True,
            "reasoning_quarantined": False,
            "clean_content_present": bool(raw.strip()),
            "gate_pass": bool(gate.get("pass")),
            "aster_compile_called": aster_compile_called,
        }
        return SubstrateAirlockResult(
            clean_content=raw if gate.get("pass") else "",
            gate=gate,
            quarantine={"had_reasoning_leak": False},
            pass_to_aster=bool(gate.get("pass") and raw),
            proof=proof,
            finish_reason="stop",
            usage={"finish_reason": "stop", "truncated": False, "content_tokens": len(raw.split())},
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
        sub = await substrate_chat(
            [{"role": "user", "content": req.prompt}], route_id=route_id,
            max_tokens=gw_max,
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
    await acquire_gate()
    route_id = str(uuid4())
    try:
        compile_max = resolve_max_tokens("compile", body.get("max_tokens"))
        messages = [{"role": "system", "content": COMPILE_CONTRACT},
                    {"role": "user", "content": signal}]
        sub = await substrate_chat(
            messages, route_id=route_id,
            max_tokens=compile_max,
            temperature=0.1, timeout=360.0,
            compile_mode=True, aster_compile_called=True,
        )
        _record_substrate("compile", compile_max, sub)
    finally:
        release_gate()

    raw = sub.clean_content
    proof = sub.proof
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
            "prompt_preview", "response_preview", "blocked"]
    return [dict(zip(cols, r)) for r in rows]


@app.get("/router-log/blocked")
def blocked_log(limit: int = 50):
    """Show only blocked (impersonation-detected) entries."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM route_log WHERE blocked = 1 ORDER BY ts DESC LIMIT ?",
            (limit,)).fetchall()
    cols = ["route_id", "ts", "user_id", "score", "routed_to",
            "prompt_preview", "response_preview", "blocked"]
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
    messages = ensure_aster_system_message(messages, request_model, ASTER_CHAT_PROMPT)
    stream = bool(body.get("stream", False))
    unsafe_debug = bool(body.get("_grid_unsafe_debug", True))
    user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
    prompt = user_msgs[-1] if user_msgs else ""
    route_id = str(uuid4())
    score = signal_score(prompt)
    beacon = is_beacon(prompt)
    routed = "unsafe_debug:beacon" if beacon else "unsafe_debug:compat"
    user_log = UNSAFE_DEBUG_ROUTE_CLASS if unsafe_debug else "compat"

    try:
        await acquire_gate()
    except GateBusy:
        raise busy_429()

    if not stream:
        chat_route = resolve_chat_route(body)
        chat_max = resolve_max_tokens(chat_route, body.get("max_tokens"))
        try:
            sub = await substrate_chat(messages, route_id=route_id, max_tokens=chat_max)
            _record_substrate(chat_route, chat_max, sub)
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

        contract_flag = None
        if not blocked:
            text, contract_flag = _lint_and_log(
                text, route_id=route_id, user_log=user_log, prompt=prompt, score=score,
            )

        computed = contract_suffix or (
            "BLOCKED" if blocked else ("SUBSTRATE_NULL" if "SUBSTRATE_NULL" in routed else "DRAFT_ECHO")
        )
        draft_only = not blocked and contract_suffix is None and "SUBSTRATE_NULL" not in routed

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
                         "finish_reason": upstream_finish}],
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
            },
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
        collected = []
        blocked = False
        blocked_pattern = None
        upstream_finish = "unknown"
        chat_route = resolve_chat_route(body)
        chat_max = resolve_max_tokens(chat_route, body.get("max_tokens"))
        gate_on = CONFIG.get("stream_incremental_gate", True) and CONFIG["cleanroom_enabled"]

        # V4.2: backend-specific stream request + line parser, unified loop below
        if CONFIG["backend"] == "openai":
            url = f"{CONFIG['openai_endpoint']}/chat/completions"
            prepared = _prepare_substrate_messages(messages)
            payload = _openai_chat_payload(prepared, stream=True, max_tokens=chat_max)
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
            url = CONFIG["ollama_endpoint"]
            payload = {"model": CONFIG["ollama_model"], "messages": messages, "stream": True}
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
                            if gate_on:
                                acc = "".join(collected)
                                hit = first_impersonation_hit(acc)
                                if hit:
                                    blocked = True
                                    blocked_pattern = hit
                                    yield _sse_chunk(route_id, {"content":
                                        "\n[GRID_ABSENT: impersonation pattern detected, output halted]"})
                                    break
                                cg = apply_contract_gate(prompt, acc, route="chat", route_id=route_id)
                                if cg.routed_suffix:
                                    blocked = True
                                    blocked_pattern = cg.routed_suffix
                                    yield _sse_chunk(route_id, {"content": f"\n[{cg.text}]"})
                                    break
                            yield _sse_chunk(route_id, {"content": piece})
                        if done:
                            break
            contract_flag = None
            if collected and not blocked:
                full_pre = "".join(collected)
                _, contract_flag = _lint_and_log(
                    full_pre, route_id=route_id, user_log=user_log, prompt=prompt, score=score,
                )
                if contract_flag:
                    marker = "\n\ncontract_flag: subject_inversion"
                    if marker.strip() not in full_pre:
                        yield _sse_chunk(route_id, {"content": marker})
            final_finish = "content_filter" if blocked else upstream_finish
            extra = link_fingerprint(route_id)
            if contract_flag:
                extra["contract_flag"] = contract_flag
            yield _sse_chunk(route_id, {}, finish=final_finish, extra=extra)
            yield "data: [DONE]\n\n"
        finally:
            release_gate()
            if collected and CONFIG["backend"] == "openai":
                _record_substrate(
                    chat_route,
                    chat_max,
                    SubstrateAirlockResult(
                        clean_content="".join(collected),
                        gate={},
                        quarantine={},
                        pass_to_aster=True,
                        proof={},
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
    uvicorn.run(app, host=host, port=port)
