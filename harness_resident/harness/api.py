from __future__ import annotations
import asyncio, os, time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .envutil import DEMO_ROOT, ensure_demo_on_path, load_harness_env
load_harness_env()
ensure_demo_on_path()

from .config import load_config
from .db import Store
from .supervisor import Supervisor
from .relay import OutboundRelayClient
from .sessions import SessionManager
from .control import ControlPlane
from .events_stream import EventStreamer

cfg=load_config()
store=Store(cfg.core.db_path)
supervisor=Supervisor(cfg,store)
sessions=SessionManager(store)
control=ControlPlane(store,supervisor)
streamer=EventStreamer(store)
supervisor_task=None
relay_task=None
stale_task=None

KNOWN_WORKERS={"local","fast","deep","full","research","cc"}

class JobCreate(BaseModel):
    channel:str="grid"
    goal:str=Field(min_length=1)
    worker:Literal["local","fast","deep","full","research","cc"]="local"
    allowed_tools:list[str]=Field(default_factory=list)
    allowed_paths:list[str]=Field(default_factory=lambda:["."])
    cloud_allowed:bool|None=None
    approval_mode:str="write_ok_no_deploy"
    read_only:bool=False
    kind:str="chat"

class ApiJobBody(BaseModel):
    worker:str="local"
    kind:str="chat"
    content:str=Field(min_length=1)
    read_only:bool=True

class SessionCreate(BaseModel):
    agent_id:str
    channel:str="grid"
    title:str=""

class SessionMessage(BaseModel):
    text:str=Field(min_length=1)
    spawn_job:bool=True
    cloud_allowed:bool|None=None
    allowed_tools:list[str]=Field(default_factory=list)
    allowed_paths:list[str]=Field(default_factory=lambda:["."])

class Decision(BaseModel):
    note:str=""

class VoiceEvent(BaseModel):
    transcript:str
    channel:str="voice"
    target:Literal["local","fast","deep","full","research","cc"]="local"
    cloud_allowed:bool|None=None

def worker_for_agent(agent_id:str)->str:
    if agent_id.startswith("local"): return "local"
    if agent_id.startswith("cc"): return "cc"
    if agent_id.startswith("fast"): return "fast"
    if agent_id.startswith("deep"): return "deep"
    if agent_id.startswith("full"): return "full"
    if agent_id.startswith("research"): return "research"
    raise HTTPException(400,f"unknown agent_id: {agent_id}")

def _gate_reason(worker:str,cloud_allowed:bool,approval_mode:str,read_only:bool=False)->str|None:
    """v1.3 执行门。危险操作默认回审批(设计 v1 链路隔离第 2 条):
    - cc write/money = 本机任意代码执行,除非调用方显式 approval_mode="auto"(须过鉴权),一律先 blocked;
    - cc read_only = L4 出生 queued 自动跑(围栏在 cc.py / create 时强制);
    - fast/deep/full/research 直连云,cloud_allowed 未显式 true 一律先 blocked(与升级路径同一条门,
      不再有免检通道;v1.2 的 if worker in {fast,deep,full,research}: ca=True 三处静默放行已全部拆除)。
    审批复用现有流:approve/resume 按钮或 POST /jobs/{id}/requeue。"""
    if worker=="cc" and read_only:
        return None
    if worker=="cc" and approval_mode!="auto":
        return "cc execution requires approval"
    if worker in {"fast","deep","full","research"} and not cloud_allowed:
        return "cloud worker requires approval or explicit cloud_allowed=true"
    return None

def create_job_internal(body:JobCreate):
    ca=cfg.policy.cloud_default if body.cloud_allowed is None else bool(body.cloud_allowed)
    ro=bool(body.read_only)
    tools=list(body.allowed_tools)
    paths=list(body.allowed_paths)
    if body.worker=="cc" and ro:
        tools=[t for t in (tools or ["Read","Grep","Glob"]) if t not in {"Bash","Write","Edit"}]
        if not tools:
            tools=["Read","Grep","Glob"]
        paths=[str(DEMO_ROOT)]
    job=store.create_job(channel=body.channel,goal=body.goal,worker=body.worker,
        allowed_tools=tools,allowed_paths=paths,
        cloud_allowed=ca,approval_mode=body.approval_mode,
        read_only=ro,kind=body.kind)
    reason=_gate_reason(body.worker,ca,body.approval_mode,read_only=ro)
    if reason:
        job=store.update_job(job["job_id"],status="blocked",last_step="awaiting_approval")
        store.append_event(job["job_id"],"blocked",{"reason":reason})
    return job

def _sync_session_gate(session_id:str,job:dict):
    """blocked 出生的 job 绑进会话后,把会话摆到 waiting_approval,手机端才会亮审批按钮。"""
    if job["status"]=="blocked":
        store.update_session(session_id,state="waiting_approval",
                             waiting_for=f"approve:{job['worker']}",last_heartbeat=time.time())
        store.append_stream_event(session_id=session_id,job_id=job["job_id"],
                                  kind="waiting_approval",
                                  payload={"reason":job["last_step"],"worker":job["worker"]})

async def relay_handler(msg:dict):
    if msg.get("type")=="create_job":
        job=create_job_internal(JobCreate(**msg["job"]))
        return {"type":"job_created","job":job,"request_id":msg.get("request_id")}
    if msg.get("type")=="get_job":
        try: job=store.get_job(msg["job_id"])
        except KeyError: return {"type":"error","error":"job_not_found","request_id":msg.get("request_id")}
        return {"type":"job","job":job,"request_id":msg.get("request_id")}
    if msg.get("type")=="list_sessions":
        return {"type":"sessions","sessions":store.list_sessions(100),"request_id":msg.get("request_id")}
    if msg.get("type")=="session_message":
        sid=msg["session_id"]
        try: s=store.get_session(sid)
        except KeyError: return {"type":"error","error":"session_not_found","request_id":msg.get("request_id")}
        text=str(msg.get("text","")).strip()
        if not text: return {"type":"error","error":"empty_message","request_id":msg.get("request_id")}
        store.append_message(sid,"user",text)
        worker=worker_for_agent(s["agent_id"])
        await supervisor.persist_external_turn(
            worker=worker,
            session_id=sid,
            role="user",
            content=text,
            source_surface=s.get("channel") or "grid",
        )
        ca=bool(msg.get("cloud_allowed",False))
        job=create_job_internal(JobCreate(channel=s["channel"],goal=text,worker=worker,
            allowed_tools=msg.get("allowed_tools",[]),allowed_paths=msg.get("allowed_paths",["."]),
            cloud_allowed=ca,approval_mode="write_ok_no_deploy"))
        store.bind_job_to_session(sid,job["job_id"])
        _sync_session_gate(sid,job)
        return {"type":"job_created","job":job,"session_id":sid,"request_id":msg.get("request_id")}
    if msg.get("type")=="create_session":
        ss=sessions.create(msg["agent_id"],msg.get("channel","grid"),msg.get("title",""))
        return {"type":"session_created","session":ss,"request_id":msg.get("request_id")}
    if msg.get("type")=="get_session":
        try: ss=store.get_session(msg["session_id"])
        except KeyError: return {"type":"error","error":"session_not_found","request_id":msg.get("request_id")}
        return {"type":"session","session":ss,"messages":store.list_messages(msg["session_id"],500),
                "request_id":msg.get("request_id")}
    if msg.get("type")=="control":
        sid=msg["session_id"]; action=msg.get("action")
        try:
            if action=="pause": ss=await control.pause(sid)
            elif action=="resume": ss=await control.resume(sid)
            elif action=="cancel": ss=await control.cancel(sid)
            elif action=="approve": ss=await control.approve(sid,msg.get("note","approved"))
            elif action=="reject": ss=await control.reject(sid,msg.get("note","rejected"))
            else: return {"type":"error","error":"bad_control","request_id":msg.get("request_id")}
        except KeyError:
            return {"type":"error","error":"session_not_found","request_id":msg.get("request_id")}
        return {"type":"control_ok","session":ss,"request_id":msg.get("request_id")}
    if msg.get("type")=="events_after":
        ev=store.list_stream_events(after_seq=int(msg.get("after_seq",0)),limit=int(msg.get("limit",1000)),
                                    session_id=msg.get("session_id"))
        return {"type":"events","events":ev,"request_id":msg.get("request_id")}
    if msg.get("type")=="context_preview":
        sid=msg["session_id"]
        try: ss=store.get_session(sid)
        except KeyError: return {"type":"error","error":"session_not_found","request_id":msg.get("request_id")}
        worker=msg.get("worker") or worker_for_agent(ss["agent_id"])
        query=str(msg.get("query") or "")
        pack=await supervisor.preview_context(worker=worker,session_id=sid,current_turn=query)
        return {"type":"context_preview","receipt":pack.receipt(),"request_id":msg.get("request_id")}
    return {"type":"error","error":"unsupported_message","request_id":msg.get("request_id")}

async def stale_loop():
    while True:
        sessions.mark_stale()
        await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app:FastAPI):
    global supervisor_task,relay_task,stale_task
    sessions.ensure_resident_sessions()
    role=os.getenv("HARNESS_ROLE","all")
    if role in {"all","supervisor"}:
        supervisor_task=asyncio.create_task(supervisor.run_forever())
    stale_task=asyncio.create_task(stale_loop())
    if cfg.relay.enabled:
        relay=OutboundRelayClient(cfg,relay_handler,event_source=lambda after: store.list_stream_events(after_seq=after,limit=500))
        relay_task=asyncio.create_task(relay.run_forever())
    yield
    for t in (supervisor_task,relay_task,stale_task):
        if t: t.cancel()
    await supervisor.stop()

app=FastAPI(title="Grid Resident Harness",version="1.3",lifespan=lifespan)

# v1.3 鉴权门:GRID_HARNESS_TOKEN 设了即全端点验 Bearer(静态页与 /health 豁免;
# 未设 = 维持 v1.2 行为并在启动日志响亮警告)。relay 信道由 relay 自己的 token 把门。
import os as _os
_HARNESS_TOKEN=_os.getenv("GRID_HARNESS_TOKEN","").strip()
_AUTH_EXEMPT_PREFIXES=("/mobile","/health")
if not _HARNESS_TOKEN:
    print("[harness] WARNING: GRID_HARNESS_TOKEN 未设置——API 无鉴权裸奔,仅限单人可信主机")

@app.middleware("http")
async def _auth_gate(request,call_next):
    if _HARNESS_TOKEN:
        p=request.url.path
        if p!="/" and not any(p.startswith(x) for x in _AUTH_EXEMPT_PREFIXES):
            if request.headers.get("authorization")!=f"Bearer {_HARNESS_TOKEN}":
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail":"unauthorized"},status_code=401)
    return await call_next(request)

MOBILE_DIR=Path(__file__).resolve().parent.parent/"mobile"
if MOBILE_DIR.exists():
    app.mount("/mobile",StaticFiles(directory=str(MOBILE_DIR),html=True),name="mobile")

@app.get("/")
async def root():
    if (MOBILE_DIR/"index.html").exists():
        return FileResponse(MOBILE_DIR/"index.html")
    return {"name":"Grid Resident Harness","version":"1.2"}

@app.get("/health")
async def health():
    from .voice_health import probe_audio8
    tts = await probe_audio8(cfg.voice.audio8)
    return {
        "ok": True,
        "service": "grid-resident-harness",
        "harness": {
            "host": cfg.harness.host,
            "port": cfg.harness.port,
        },
        "gateway_ready": await supervisor.gateway.ready(),
        "db_path": cfg.core.db_path,
        "relay_enabled": cfg.relay.enabled,
        "sessions": len(store.list_sessions(1000)),
        "voice": {
            "provider": cfg.voice.provider,
            "fallback_provider": cfg.voice.fallback_provider,
            "fallback_enabled": cfg.voice.fallback_enabled,
            "audio8": tts,
        },
        "memory": {
            "enabled": cfg.memory.enabled,
            "context_owner": cfg.memory.context_owner,
            "subject_id": cfg.memory.subject_id,
            "strict_domain_isolation": cfg.memory.strict_domain_isolation,
            "worker_domains": {
                "local": cfg.context.local.memory_domain,
                "cc": cfg.context.cc.memory_domain,
                "fast": cfg.context.fast.memory_domain,
                "deep": cfg.context.deep.memory_domain,
                "full": cfg.context.full.memory_domain,
                "research": cfg.context.research.memory_domain,
            },
        },
    }

@app.get("/api/capabilities")
async def api_capabilities():
    from app.harness.resource_gate import export_capability_surface
    surface=export_capability_surface()
    surface["web.fetch"]="DENIED"
    return surface

@app.post("/api/jobs")
async def api_create_job(body:ApiJobBody):
    if body.worker not in KNOWN_WORKERS:
        job=store.create_job(channel="grid",goal=body.content,worker=body.worker,
            allowed_tools=[],allowed_paths=["."],cloud_allowed=False,
            approval_mode="write_ok_no_deploy",read_only=bool(body.read_only),
            kind=body.kind,status="blocked",last_step="UNKNOWN_WORKER")
        store.append_event(job["job_id"],"blocked",{"reason":"UNKNOWN_WORKER"})
        return {"job_id":job["job_id"],"status":job["status"],"last_step":job["last_step"]}
    job=create_job_internal(JobCreate(
        channel="grid",goal=body.content,worker=body.worker,
        cloud_allowed=True if body.worker=="local" else False,
        approval_mode="auto" if body.read_only else "write_ok_no_deploy",
        read_only=bool(body.read_only),kind=body.kind,
    ))
    return {"job_id":job["job_id"],"status":job["status"],"last_step":job.get("last_step")}

@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id:str):
    try: job=store.get_job(job_id)
    except KeyError: raise HTTPException(404,"job not found")
    return {
        "job_id":job["job_id"],
        "status":job["status"],
        "worker":job["worker"],
        "kind":job.get("kind"),
        "read_only":job.get("read_only"),
        "last_step":job.get("last_step"),
        "receipt_event_id":job.get("receipt_event_id"),
        "events":store.list_events(job_id),
    }

@app.post("/jobs")
async def create_job(body:JobCreate): return create_job_internal(body)

@app.get("/jobs")
async def list_jobs(limit:int=100): return store.list_jobs(limit)

@app.get("/jobs/{job_id}")
async def get_job(job_id:str):
    try: job=store.get_job(job_id)
    except KeyError: raise HTTPException(404,"job not found")
    return {**job,"events":store.list_events(job_id)}

@app.post("/jobs/{job_id}/requeue")
async def requeue(job_id:str):
    try: job=store.get_job(job_id)
    except KeyError: raise HTTPException(404,"job not found")
    if job["status"] not in {"failed","blocked","interrupted"}:
        raise HTTPException(409,f"cannot requeue from {job['status']}")
    if job.get("worker")=="cc" or job.get("kind")=="money_moving" or not job.get("read_only",True):
        raise HTTPException(409,"requeue only for read_only")
    return store.update_job(job_id,status="queued",last_step="manual_requeue")

@app.post("/sessions")
async def create_session(body:SessionCreate):
    return sessions.create(body.agent_id,body.channel,body.title)

@app.get("/sessions")
async def list_sessions(limit:int=100):
    return store.list_sessions(limit)

@app.get("/sessions/{session_id}")
async def get_session(session_id:str):
    try: s=store.get_session(session_id)
    except KeyError: raise HTTPException(404,"session not found")
    return {**s,"messages":store.list_messages(session_id,500)}

@app.post("/sessions/{session_id}/message")
async def session_message(session_id:str,body:SessionMessage):
    try: s=store.get_session(session_id)
    except KeyError: raise HTTPException(404,"session not found")
    msg=control.message(session_id,body.text)
    worker=worker_for_agent(s["agent_id"])
    memory_write=await supervisor.persist_external_turn(
        worker=worker,
        session_id=session_id,
        role="user",
        content=body.text,
        source_surface=s.get("channel") or "grid",
    )
    if not body.spawn_job:
        return {"message":msg,"memory_write":memory_write,"session":store.get_session(session_id)}
    job=create_job_internal(JobCreate(channel=s["channel"],goal=body.text,worker=worker,
        allowed_tools=body.allowed_tools,allowed_paths=body.allowed_paths,
        cloud_allowed=body.cloud_allowed,approval_mode="write_ok_no_deploy"))
    store.bind_job_to_session(session_id,job["job_id"])
    _sync_session_gate(session_id,job)
    return {"message":msg,"memory_write":memory_write,"job":job,"session":store.get_session(session_id)}

@app.get("/sessions/{session_id}/context-preview")
async def context_preview(
    session_id:str,
    worker:Literal["local","cc","fast","deep","full","research"]|None=None,
    query:str="",
    include_content:bool=False,
):
    try: ss=store.get_session(session_id)
    except KeyError: raise HTTPException(404,"session not found")
    actual_worker=worker or worker_for_agent(ss["agent_id"])
    pack=await supervisor.preview_context(
        worker=actual_worker,
        session_id=session_id,
        current_turn=query,
    )
    out={"receipt":pack.receipt()}
    if include_content:
        out["layers"]={
            "stable_core":pack.stable_core.content,
            "active_state":pack.active_state.content,
            "recent_turns":pack.recent_turns,
            "recall":pack.recall.content,
            "current_turn":pack.current_turn,
        }
    return out

@app.post("/sessions/{session_id}/pause")
async def pause(session_id:str): return await control.pause(session_id)

@app.post("/sessions/{session_id}/resume")
async def resume(session_id:str): return await control.resume(session_id)

@app.post("/sessions/{session_id}/cancel")
async def cancel(session_id:str): return await control.cancel(session_id)

@app.post("/sessions/{session_id}/approve")
async def approve(session_id:str,body:Decision): return await control.approve(session_id,body.note or "approved")

@app.post("/sessions/{session_id}/reject")
async def reject(session_id:str,body:Decision): return await control.reject(session_id,body.note or "rejected")

@app.get("/events")
async def events(after_seq:int=0,session_id:str|None=None,limit:int=1000):
    return store.list_stream_events(after_seq=after_seq,session_id=session_id,limit=limit)

@app.websocket("/ws/events")
async def ws_events(ws:WebSocket,after_seq:int=0,session_id:str|None=None):
    # HTTP 中间件不覆盖 WS:token 走 query 参数或 Authorization 头,二选一命中即放行
    if _HARNESS_TOKEN:
        supplied=ws.query_params.get("token","") or ws.headers.get("authorization","").removeprefix("Bearer ").strip()
        if supplied!=_HARNESS_TOKEN:
            await ws.close(code=4401); return
    await streamer.serve(ws,after_seq=after_seq,session_id=session_id)

@app.post("/events/voice")
async def voice_event(body:VoiceEvent):
    agent_id={"local":"local-main","cc":"cc-main","fast":"fast-on-demand","deep":"deep-on-demand","full":"full-on-demand","research":"research-on-demand"}[body.target]
    s=sessions.create(agent_id,channel=body.channel,title=f"voice:{body.target}")
    msg=SessionMessage(text=body.transcript,spawn_job=True,cloud_allowed=body.cloud_allowed)
    return await session_message(s["session_id"],msg)
