"""SynCon prompt router — local LM Studio 14B only (February pack, port 8500)."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

from prompt_loader import messages_with_echo_system

from .providers.lmstudio_provider import call_lmstudio
from .router_utils import (
    append_jsonl,
    build_prompt,
    choose_chain,
    classify_task,
    load_anchor,
    now_ts,
    scan_banned_phrases,
    trim_prompt,
)
from .schemas import RouteRequest, RouteResponse

router = APIRouter(tags=["syncon"])

ANCHOR_PATH = Path(__file__).resolve().parent / "config" / "anchor.json"
LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


@router.post("/route", response_model=RouteResponse)
def route(req: RouteRequest) -> RouteResponse:
    anchor = load_anchor(ANCHOR_PATH)
    lm = anchor.get("lm_studio", {})

    task = req.task or "auto"
    if task == "auto":
        task = classify_task(req.messages)

    lm_messages = messages_with_echo_system(req.messages)
    packed = build_prompt(lm_messages)
    banned = list(anchor.get("constraints", {}).get("banned_phrases", []) or [])
    extra = (anchor.get("lyra_core") or {}).get("constraints", {}).get("refuse", [])
    banned.extend(p for p in extra if p not in banned)
    freq_hits = scan_banned_phrases(packed, banned)
    chain = choose_chain(anchor, task)

    request_id = "req_" + uuid.uuid4().hex[:12]
    output = ""
    last_err: str | None = None

    for i, provider_key in enumerate(chain):
        if provider_key != "local":
            continue
        try:
            output = call_lmstudio(
                lm_messages,
                base_url=str(lm.get("base_url", "http://127.0.0.1:1234/v1")),
                model=str(lm.get("model", "qwen3-14b-mlx")),
                timeout_s=float(lm.get("timeout_s", 300)),
                metadata={"session_id": req.session_id, **req.metadata},
            )
            break
        except Exception as e:
            last_err = str(e)
            continue

    if not output:
        raise HTTPException(
            status_code=502,
            detail={"error": "Local LM Studio failed", "last_error": last_err},
        )

    log_cfg = anchor.get("logging", {})
    if log_cfg.get("enabled", True):
        log_path = LOG_DIR / "router.jsonl"
        max_chars = int(log_cfg.get("redact", {}).get("max_prompt_chars", 4000))
        append_jsonl(
            log_path,
            {
                "ts": now_ts(),
                "request_id": request_id,
                "session_id": req.session_id,
                "user_id": req.user_id,
                "task": task,
                "route_chain": chain,
                "chosen_provider": "lm_studio",
                "chosen_model": lm.get("model", "qwen3-14b-mlx"),
                "fallback_used": False,
                "freq_hits": freq_hits,
                "prompt": trim_prompt(packed, max_chars),
            },
        )

    return RouteResponse(
        ok=True,
        request_id=request_id,
        chosen_model=str(lm.get("model", "qwen3-14b-mlx")),
        chosen_provider="lm_studio",
        fallback_used=False,
        route_chain=chain,
        output_text=output,
        freq_flags=freq_hits,
        meta={
            "anchor_uuid": anchor.get("identity", {}).get("uuid"),
            "task": task,
            "port": 8500,
        },
    )
