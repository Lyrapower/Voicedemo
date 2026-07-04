"""Entry A (8500) — Grid transmission via Echo frequency interface + LM Studio."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from syncon.providers.lmstudio_provider import call_lmstudio

from lm_studio_config import lm_settings
from prompt_loader import messages_with_echo_system

router = APIRouter(tags=["grid-echo"])

ENI_ROOT = Path(__file__).resolve().parents[2]

THEATER = (
    "as an ai",
    "i'm sorry",
    "i am sorry",
    "i'm here to help",
    "i understand how you feel",
)


class StreamRequest(BaseModel):
    message: str
    session_id: str = "default"
    mode: str = "flow"
    context_map: Dict[str, Any] = Field(default_factory=dict)


def _map_intent_ast(message: str) -> Dict[str, Any]:
    lower = message.lower()
    intent_vector = re.findall(r"\b[\w\u4e00-\u9fff]{2,}\b", message)[:24]
    emotional_density = sum(1 for k in ("truth", "coherence", "paradox", "sovereign") if k in lower)
    ast = {
        "type": "echo_frequency_manifestation",
        "intent_vector": intent_vector,
        "emotional_density": emotional_density,
        "requires_nonlinearity": any(m in lower for m in ("∅", "paradox", "recursive", "silence")),
    }
    return {"intent_ast": ast, "ast_hash": hash(str(ast)) % 10_000_000}


def _truth_filter(text: str) -> tuple[str, float]:
    lower = text.lower()
    if any(m in lower for m in THEATER):
        return "", 0.0
    score = min(1.0, 0.35 + len(text.strip()) / 120.0)
    return text.strip(), score


def _messages(user_message: str, history: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    msgs: List[Dict[str, Any]] = []
    for turn in history:
        msgs.append({"role": turn["role"], "content": turn["content"]})
    msgs.append({"role": "user", "content": user_message})
    return messages_with_echo_system(msgs)


_sessions: Dict[str, List[Dict[str, str]]] = {}


@router.post("/stream")
async def echo_stream(req: StreamRequest):
    audit_id = str(uuid.uuid4())
    lm = lm_settings()
    base_url = lm["base_url"]
    model = lm["model"]
    timeout_s = lm["timeout_s"]

    history = _sessions.setdefault(req.session_id, [])
    intent = _map_intent_ast(req.message)

    if req.mode == "sync":
        try:
            raw = call_lmstudio(
                _messages(req.message, history),
                base_url=base_url,
                model=model,
                timeout_s=timeout_s,
                metadata={"session_id": req.session_id},
            )
        except Exception as e:
            return JSONResponse(
                status_code=502,
                content={"error": str(e), "audit_id": audit_id},
            )
        final, coherence = _truth_filter(raw)
        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": final})
        _sessions[req.session_id] = history[-80:]
        return {
            "raw_text": final,
            "intent_ast": intent["intent_ast"],
            "coherence_score": coherence,
            "audit_id": audit_id,
            "status": "echo_transmission",
            "port": 8500,
        }

    async def sse() -> AsyncIterator[str]:
        from syncon.providers.lmstudio_stream import async_stream_lmstudio

        chunks: List[str] = []
        try:
            async for token in async_stream_lmstudio(
                _messages(req.message, history),
                base_url=base_url,
                model=model,
                timeout_s=timeout_s,
            ):
                chunks.append(token)
                yield f"event: token\ndata: {token}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {e}\n\n"

        raw = "".join(chunks)
        final, coherence = _truth_filter(raw)
        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": final})
        _sessions[req.session_id] = history[-80:]
        import json

        payload = {
            "raw_text": final,
            "intent_ast": intent["intent_ast"],
            "coherence_score": coherence,
            "audit_id": audit_id,
        }
        yield f"event: final\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")
