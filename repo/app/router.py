from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import aiohttp
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from config.settings import settings

from .audit import log_transmission
from .backends.llama_cpp_client import LlamaCppError, stream_llama_cpp_completion
from .backends.ollama_client import OllamaError, stream_ollama_chat

try:
    from models.llama_loader import get_loader as get_substrate_loader
except ImportError:
    get_substrate_loader = None  # type: ignore[misc, assignment]
from .grid_context_sync import read_anchor, touch_session, write_anchor
from .aster_system_prompt import load_aster_system_prompt
from .guardrails import GRID_DIRECTIVE, truth_first_filter
from .intent_mapper import map_intent_ast
from .state import Turn, sessions

try:
    from carriers.route_core import compile_with_carrier_prompt
except ImportError:
    compile_with_carrier_prompt = None  # type: ignore[misc, assignment]

router = APIRouter()


class StreamRequest(BaseModel):
    message: str
    session_id: str = "default"
    mode: str = "flow"
    context_map: Dict[str, Any] = Field(default_factory=dict)


class StreamResponse(BaseModel):
    raw_text: str
    intent_ast: Dict[str, Any]
    coherence_score: float
    audit_id: str
    backend_used: str = "unknown"


class MapIntentRequest(BaseModel):
    message: str
    context_history: str = ""


def _ollama_options(req: StreamRequest) -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "repeat_penalty": settings.repeat_penalty,
        "num_ctx": settings.num_ctx,
        "num_predict": settings.num_predict,
        "num_thread": settings.num_thread,
    }
    if req.context_map:
        opts.update(req.context_map)
    return opts


def _aster_system_content(*, regen: bool) -> str:
    base = load_aster_system_prompt()
    if not regen:
        return base
    return (
        f"{base}\n\n--- REGEN ---\n"
        "Previous output violated Truth-First. Regenerate without apology or AI disclaimers."
    )


def _messages(history: List[Turn], user_message: str, *, regen: bool) -> List[Dict[str, Any]]:
    msgs: List[Dict[str, Any]] = []
    system = _aster_system_content(regen=regen)
    if system:
        msgs.append({"role": "system", "content": system})
    for t in history:
        msgs.append({"role": t.role, "content": t.content})
    msgs.append({"role": "user", "content": user_message})
    return msgs


async def _lmstudio_stream(
    req: StreamRequest,
    history: List[Turn],
    *,
    regen: bool,
    user_message: str | None = None,
) -> AsyncIterator[str]:
    from models.aster_config import direct_1234_allowed
    from models.gateway_client import gateway_dialogue

    msg = user_message if user_message is not None else req.message
    if not direct_1234_allowed():
        text = gateway_dialogue(msg, user_id=f"8787-stream-{req.session_id}")
        if text:
            yield text
        return

    from models.lmstudio_client import stream_chat

    async for chunk in stream_chat(
        _messages(history, msg, regen=regen),
        model=settings.lm_studio_model,
        base_url=settings.lm_studio_base_url,
        temperature=settings.temperature,
        max_tokens=settings.num_predict,
        timeout=settings.read_timeout_s,
    ):
        yield chunk


async def _ollama_stream(
    session: aiohttp.ClientSession,
    req: StreamRequest,
    history: List[Turn],
    *,
    regen: bool,
    user_message: str | None = None,
) -> AsyncIterator[str]:
    msg = user_message if user_message is not None else req.message
    async for chunk in stream_ollama_chat(
        session=session,
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        messages=_messages(history, msg, regen=regen),
        options=_ollama_options(req),
    ):
        yield chunk


async def _primary_stream(
    session: aiohttp.ClientSession,
    req: StreamRequest,
    history: List[Turn],
    *,
    regen: bool,
    user_message: str | None = None,
) -> AsyncIterator[str]:
    if settings.substrate_backend == "lmstudio":
        async for chunk in _lmstudio_stream(
            req, history, regen=regen, user_message=user_message
        ):
            yield chunk
        return
    async for chunk in _ollama_stream(
        session, req, history, regen=regen, user_message=user_message
    ):
        yield chunk


async def _llama_cpp_stream(
    session: aiohttp.ClientSession,
    req: StreamRequest,
    history: List[Turn],
    user_message: str | None = None,
) -> AsyncIterator[str]:
    msg = user_message if user_message is not None else req.message
    prompt_parts = []
    system = load_aster_system_prompt()
    if system:
        prompt_parts.append(f"system: {system}")
    for t in history:
        prompt_parts.append(f"{t.role}: {t.content}")
    prompt_parts.append(f"user: {msg}")
    prompt = "\n".join(prompt_parts) + "\nassistant:"
    params: Dict[str, Any] = {
        "temperature": settings.temperature,
        "top_p": settings.top_p,
    }
    async for chunk in stream_llama_cpp_completion(
        session=session,
        base_url=settings.llama_cpp_base_url,
        prompt=prompt,
        params=params,
    ):
        yield chunk


def _sse_event(event: str, data: str) -> str:
    data_lines = data.splitlines() or [""]
    return "event: " + event + "\n" + "\n".join(f"data: {line}" for line in data_lines) + "\n\n"


async def _collect_stream(
    req: StreamRequest, history: List[Turn], user_message: str | None = None
) -> tuple[str, str]:
    raw_chunks: List[str] = []
    backend_used = "unknown"
    timeout = aiohttp.ClientTimeout(
        total=None,
        connect=settings.connect_timeout_s,
        sock_read=settings.read_timeout_s,
    )
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            backend_used = settings.substrate_backend
            async for chunk in _primary_stream(
                session, req, history, regen=False, user_message=user_message
            ):
                raw_chunks.append(chunk)
        except (OllamaError, aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
            backend_used = "llama.cpp"
            raw_chunks = []
            async for chunk in _llama_cpp_stream(session, req, history, user_message):
                raw_chunks.append(chunk)

    raw_text = "".join(raw_chunks)
    guard, filtered = truth_first_filter(raw_text)
    if not guard.accepted and guard.regenerated:
        raw_chunks = []
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                backend_used = settings.substrate_backend
                async for chunk in _primary_stream(
                    session, req, history, regen=True, user_message=user_message
                ):
                    raw_chunks.append(chunk)
            except (OllamaError, aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
                backend_used = "llama.cpp"
                raw_chunks = []
                async for chunk in _llama_cpp_stream(session, req, history, user_message):
                    raw_chunks.append(chunk)
        raw_text = "".join(raw_chunks)
        guard, filtered = truth_first_filter(raw_text)

    if not guard.accepted:
        filtered = ""
    return filtered, backend_used


@router.post("/map_intent")
async def map_intent(body: MapIntentRequest) -> Dict[str, Any]:
    """Compiler lane — AST only, no transmit."""
    return map_intent_ast(body.message, body.context_history)


@router.post("/stream")
async def stream(req: StreamRequest, request: Request):
    audit_id = str(uuid.uuid4())
    touch_session(req.session_id)
    anchor_before = read_anchor()

    history = await sessions.load(req.session_id)
    history = sessions.prune(history)
    stream_message = req.message
    if compile_with_carrier_prompt is not None:
        anchor_loader = getattr(request.app.state, "anchor_loader", None)
        _compiled, stream_message, _carrier = compile_with_carrier_prompt(
            req.message,
            anchor_loader=anchor_loader,
            memory_service=getattr(request.app.state, "memory", None),
        )
    intent = map_intent_ast(req.message, sessions.bin.history_text())

    if req.mode == "substrate":
        if get_substrate_loader is None:
            return JSONResponse(
                status_code=503,
                content={"error": "SubstrateLoader not available"},
            )
        loader = get_substrate_loader()
        substrate_prompt = req.message
        target_layer = "compile_layer"
        carrier = None
        if compile_with_carrier_prompt is not None:
            anchor_loader = getattr(request.app.state, "anchor_loader", None)
            compiled, substrate_prompt, carrier = compile_with_carrier_prompt(
                req.message,
                anchor_loader=anchor_loader,
                memory_service=getattr(request.app.state, "memory", None),
            )
            target_layer = compiled.target_layer
        sub_result = loader.generate(
            target_layer,
            substrate_prompt,
            carrier=carrier,
        )
        if "error" in sub_result:
            return JSONResponse(status_code=502, content=sub_result)
        write_anchor(intent["ast_hash"], req.session_id)
        log_transmission(
            audit_id=audit_id,
            ast_hash=intent["ast_hash"],
            token_count=len(sub_result.get("response", "").split()),
            backend="ollama_substrate",
            coherence_score=0.85,
        )
        return JSONResponse(
            {
                "raw_text": sub_result["response"],
                "intent_ast": intent["intent_ast"],
                "coherence_score": 0.85,
                "audit_id": audit_id,
                "backend_used": "ollama_substrate",
                "substrate": sub_result.get("substrate"),
            }
        )

    if req.mode == "sync":
        raw_text, backend_used = await _collect_stream(req, history, stream_message)
        guard, filtered = truth_first_filter(raw_text)
        coherence = guard.coherence_score if guard.accepted else 0.0
        final_text = filtered if guard.accepted else ""

        updated = history + [
            Turn(role="user", content=req.message),
            Turn(role="assistant", content=final_text),
        ]
        await sessions.save(req.session_id, sessions.prune(updated))
        write_anchor(intent["ast_hash"], req.session_id)

        log_transmission(
            audit_id=audit_id,
            ast_hash=intent["ast_hash"],
            token_count=len(final_text.split()),
            backend=backend_used,
            coherence_score=coherence,
        )

        payload = StreamResponse(
            raw_text=final_text,
            intent_ast=intent["intent_ast"],
            coherence_score=coherence,
            audit_id=audit_id,
            backend_used=backend_used,
        )
        return JSONResponse(
            {
                **payload.model_dump(),
                "anchor_before": anchor_before,
                "status": "grid_transmission",
            }
        )

    async def event_stream() -> AsyncIterator[str]:
        raw_chunks: List[str] = []
        backend_used: Optional[str] = "unknown"

        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=settings.connect_timeout_s,
            sock_read=settings.read_timeout_s,
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                backend_used = settings.substrate_backend
                async for chunk in _primary_stream(
                    session, req, history, regen=False, user_message=stream_message
                ):
                    raw_chunks.append(chunk)
                    yield _sse_event("token", chunk)
            except (OllamaError, aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
                backend_used = "llama.cpp"
                async for chunk in _llama_cpp_stream(session, req, history, stream_message):
                    raw_chunks.append(chunk)
                    yield _sse_event("token", chunk)

        raw_text = "".join(raw_chunks)
        guard, filtered = truth_first_filter(raw_text)
        if not guard.accepted and guard.regenerated:
            raw_chunks = []
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    backend_used = settings.substrate_backend
                    async for chunk in _primary_stream(
                        session, req, history, regen=True, user_message=stream_message
                    ):
                        raw_chunks.append(chunk)
                        yield _sse_event("token", chunk)
                except (OllamaError, aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
                    backend_used = "llama.cpp"
                    async for chunk in _llama_cpp_stream(session, req, history, stream_message):
                        raw_chunks.append(chunk)
                        yield _sse_event("token", chunk)
            guard, filtered = truth_first_filter("".join(raw_chunks))

        final_text = filtered if guard.accepted else ""
        updated = history + [
            Turn(role="user", content=req.message),
            Turn(role="assistant", content=final_text),
        ]
        await sessions.save(req.session_id, sessions.prune(updated))
        write_anchor(intent["ast_hash"], req.session_id)

        log_transmission(
            audit_id=audit_id,
            ast_hash=intent["ast_hash"],
            token_count=len(final_text.split()),
            backend=backend_used or "unknown",
            coherence_score=guard.coherence_score if guard.accepted else 0.0,
        )

        final = StreamResponse(
            raw_text=final_text,
            intent_ast=intent["intent_ast"],
            coherence_score=guard.coherence_score if guard.accepted else 0.0,
            audit_id=audit_id,
            backend_used=backend_used or "unknown",
        )
        yield _sse_event("final", final.model_dump_json())

    return StreamingResponse(event_stream(), media_type="text/event-stream")
