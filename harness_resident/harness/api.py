from __future__ import annotations
import asyncio, json, os, time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from .ops import classify_steps, execute_steps, parse_action_plan, worker_output_json
from .topology import (
    CORS_ORIGIN, clamp_latency_ms, duration_ms_for, last_nonempty_line,
    provenance_line_raw, record_ack_receipt, record_grid_action, record_tool_receipt,
    resolve_scope, worker_output_from_events,
)

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
mission_task=None

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
    origin:str=""
    context_hash:str=""
    lane:str|None=None
    search:list|dict|None=None
    latency_budget_ms:int|None=None
    steps:list=Field(default_factory=list)

class ApiJobBody(BaseModel):
    worker:str="local"
    kind:str="chat"
    content:str=Field(min_length=1)
    read_only:bool=False
    origin:str=""
    context_hash:str=""
    lane:str|None=None
    latency_budget_ms:int|None=None
    steps:list=Field(default_factory=list)

class MissionCreate(BaseModel):
    goal:str=Field(min_length=1)
    lane:str="scout"
    worker:str="deep"
    budget_hops:int=0
    budget_tokens:int=0
    budget_wall_s:float=0.0
    budget_usd:float=0.0
    stop_conditions:list[str]=Field(default_factory=list)
    tools:list[str]=Field(default_factory=list)
    search:list|dict|None=None
    created_by:str="manual"
    status:str="proposed"
    read_only:bool=True
    origin:str=""
    context_hash:str=""
    latency_budget_ms:int|None=None
    steps:list=Field(default_factory=list)

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

def _cc_timeout_ms()->int:
    return max(1,int(getattr(cfg.cc,"timeout_seconds",120))*1000)

def create_job_internal(body:JobCreate, *, scope:str="full"):
    origin=(body.origin or "").strip()
    ctx=(body.context_hash or "").strip()
    if origin=="grid_compiled" and not ctx:
        raise HTTPException(400,"grid_compiled requires context_hash")
    if origin=="grid_c_confirm" and not ctx:
        raise HTTPException(400,"grid_c_confirm requires context_hash")
    cap=_cc_timeout_ms()
    latency=clamp_latency_ms(body.latency_budget_ms,cap_ms=cap)
    classified=None
    worker=body.worker
    ro=bool(body.read_only)
    ack=False
    status="queued"
    last_step=None
    tool_out=None
    steps=list(body.steps or [])
    if origin!="grid_c_confirm" and (not steps or not any(isinstance(s,dict) and s.get("target") for s in steps)):
        parsed=parse_action_plan(body.goal)
        if parsed:
            steps=parsed
    if origin=="grid_c_confirm":
        steps=[]
    if origin=="grid_compiled" or steps:
        classified=classify_steps(steps)
        if classified["blocked"]:
            if scope in {"h1","page"}:
                raise HTTPException(403,"read_only scope cannot post non read_only op")
            worker="cc"
            ro=False
            status="blocked"
            last_step="OP_DENIED"
        else:
            worker=classified["worker"] or "cc"
            ro=bool(classified["read_only"])
            ack=bool(classified["topology_ack"])
            if classified["kind"]=="ack":
                status="done"
                last_step="topology_ack"
            elif classified.get("executor")=="tool":
                try:
                    tool_out=execute_steps(steps,allowed_paths=[str(DEMO_ROOT)])
                except (PermissionError, FileNotFoundError, IsADirectoryError, OSError) as exc:
                    if scope in {"h1","page"}:
                        raise HTTPException(403,"read_only scope cannot post non read_only op")
                    worker="cc"
                    ro=False
                    status="blocked"
                    last_step="OP_DENIED"
                    tool_out={"error":str(exc)}
                else:
                    status="done"
                    last_step="fs_tool"
                    ack=bool(ack or tool_out.get("topology_ack"))
                    worker="cc"
                    ro=True
            else:
                status="queued"
                last_step=None
        if scope in {"h1","page"} and not ro:
            raise HTTPException(403,"read_only scope cannot post non read_only op")
    ca=cfg.policy.cloud_default if body.cloud_allowed is None else bool(body.cloud_allowed)
    tools=list(body.allowed_tools)
    paths=list(body.allowed_paths)
    if worker=="cc" and ro:
        tools=[t for t in (tools or ["Read","Grep","Glob"]) if t not in {"Bash","Write","Edit"}]
        if not tools:
            tools=["Read","Grep","Glob"]
        paths=[str(DEMO_ROOT)]
    # lane resolution (衔拍2): mission.lane flows in via runner; H1/ACTION (grid_compiled/
    # grid_c_confirm) gets the ops-table default "deep"; manual /api/jobs submit MUST
    # carry lane explicitly or 400. goal text never overrides an explicit lane.
    if body.lane:
        lane=body.lane
    elif origin in ("grid_compiled","grid_c_confirm"):
        lane="deep"          # H1/ACTION ops-table default lane
    elif origin:
        lane=""               # other origin-bearing (telegram/scheduled) legacy default
    else:
        raise HTTPException(400,"lane is required for manual /api/jobs submit (got no origin, no lane)")
    job=store.create_job(channel=body.channel,goal=body.goal,worker=worker,
        allowed_tools=tools,allowed_paths=paths,
        cloud_allowed=ca,approval_mode=body.approval_mode,
        read_only=ro,kind=body.kind,status=status,last_step=last_step,
        origin=origin,context_hash=ctx,latency_budget_ms=latency,
        steps=steps if steps else list(body.steps or []),topology_ack=ack,lane=lane,
        search=body.search)
    if origin=="grid_compiled" or ctx:
        try: record_grid_action(job)
        except Exception: pass
    if status=="blocked":
        store.append_event(job["job_id"],"blocked",{"reason":last_step or "OP_DENIED"})
        try:
            ev=record_ack_receipt(job,status="DENIED",executed=False,error=last_step or "OP_DENIED")
            line=provenance_line_raw(ev.get("event_id") or "")
            store.put_job_receipt(event_id=ev.get("event_id") or job["job_id"],
                                  job_id=job["job_id"],receipt_line=line or json.dumps(ev,ensure_ascii=False),
                                  worker_output="")
            store.update_job(job["job_id"],receipt_event_id=ev.get("event_id"))
        except Exception:
            pass
        return store.get_job(job["job_id"])
    if status=="done" and last_step=="topology_ack":
        try:
            ev=record_ack_receipt(job,status="EXECUTED",executed=True)
            line=provenance_line_raw(ev.get("event_id") or "")
            store.put_job_receipt(event_id=ev.get("event_id") or job["job_id"],
                                  job_id=job["job_id"],receipt_line=line or json.dumps(ev,ensure_ascii=False),
                                  worker_output="")
            store.update_job(job["job_id"],receipt_event_id=ev.get("event_id"))
            store.append_stream_event(session_id=None,job_id=job["job_id"],kind="receipt",
                                      payload={"event_id":ev.get("event_id"),"job_id":job["job_id"],
                                               "context_hash":ctx,"status":"EXECUTED","topology_ack":True,
                                               "receipt_line":line})
        except Exception:
            pass
        return store.get_job(job["job_id"])
    if status=="done" and last_step=="fs_tool":
        output=worker_output_json(tool_out or {})
        store.append_event(job["job_id"],"job_result",tool_out or {})
        try:
            ev=record_tool_receipt(job,status="EXECUTED",executed=True)
            line=provenance_line_raw(ev.get("event_id") or "")
            store.put_job_receipt(event_id=ev.get("event_id") or job["job_id"],
                                  job_id=job["job_id"],receipt_line=line or json.dumps(ev,ensure_ascii=False),
                                  worker_output=output)
            store.update_job(job["job_id"],receipt_event_id=ev.get("event_id"))
            store.append_stream_event(session_id=None,job_id=job["job_id"],kind="receipt",
                                      payload={"event_id":ev.get("event_id"),"job_id":job["job_id"],
                                               "context_hash":ctx,"status":"EXECUTED",
                                               "topology_ack":ack,"executor":"tool",
                                               "receipt_line":line})
        except Exception:
            pass
        return store.get_job(job["job_id"])
    reason=_gate_reason(worker,ca,body.approval_mode,read_only=ro)
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
    global supervisor_task,relay_task,stale_task,mission_task
    sessions.ensure_resident_sessions()
    role=os.getenv("HARNESS_ROLE","all")
    if role in {"all","supervisor"}:
        supervisor_task=asyncio.create_task(supervisor.run_forever())
        from mission.runner import run_mission_loop
        mission_task=asyncio.create_task(run_mission_loop(supervisor,store))
    stale_task=asyncio.create_task(stale_loop())
    if cfg.relay.enabled:
        relay=OutboundRelayClient(cfg,relay_handler,event_source=lambda after: store.list_stream_events(after_seq=after,limit=500))
        relay_task=asyncio.create_task(relay.run_forever())
    yield
    for t in (supervisor_task,relay_task,stale_task,mission_task):
        if t: t.cancel()
    await supervisor.stop()

app=FastAPI(title="Grid Resident Harness",version="1.3",lifespan=lifespan)

# v1.3 鉴权门:GRID_HARNESS_TOKEN 设了即全端点验 Bearer(静态页与 /health 豁免;
# 未设 = 维持 v1.2 行为并在启动日志响亮警告)。relay 信道由 relay 自己的 token 把门。
import os as _os
_HARNESS_TOKEN=_os.getenv("GRID_HARNESS_TOKEN","").strip()
_AUTH_EXEMPT_PREFIXES=("/mobile","/health","/app")
if not _HARNESS_TOKEN and not _os.getenv("GRID_HARNESS_H1_TOKEN","").strip() and not _os.getenv("GRID_HARNESS_PAGE_TOKEN","").strip():
    print("[harness] WARNING: GRID_HARNESS_TOKEN 未设置——API 无鉴权裸奔,仅限单人可信主机")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_ORIGIN, "http://localhost:8501"],
    allow_methods=["GET","POST","HEAD","OPTIONS"],
    allow_headers=["Authorization","Content-Type"],
)

def _bearer(request)->str:
    auth=request.headers.get("authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""

@app.middleware("http")
async def _auth_gate(request,call_next):
    p=request.url.path
    if p=="/" or request.method=="OPTIONS" or any(p.startswith(x) for x in _AUTH_EXEMPT_PREFIXES):
        return await call_next(request)
    scope=resolve_scope(_bearer(request))
    if scope is None:
        return JSONResponse({"detail":"unauthorized"},status_code=401)
    request.state.scope=scope
    if scope=="page" and request.method not in {"GET","HEAD","OPTIONS"}:
        return JSONResponse({"detail":"page scope is GET only"},status_code=403)
    if scope=="h1" and request.method not in {"GET","HEAD","OPTIONS","POST"}:
        return JSONResponse({"detail":"h1 scope denied"},status_code=403)
    if scope=="h1" and request.method=="POST" and not p.startswith("/api/jobs"):
        return JSONResponse({"detail":"h1 scope POST only /api/jobs"},status_code=403)
    return await call_next(request)

MOBILE_DIR=Path(__file__).resolve().parent.parent/"mobile"
if MOBILE_DIR.exists():
    app.mount("/mobile",StaticFiles(directory=str(MOBILE_DIR),html=True),name="mobile")

@app.get("/")
async def root():
    if (MOBILE_DIR/"index.html").exists():
        return FileResponse(MOBILE_DIR/"index.html")
    return {"name":"Grid Resident Harness","version":"1.2"}

@app.get("/app/missions.html")
async def missions_page():
    p = Path(__file__).resolve().parent.parent / "static" / "missions.html"
    return FileResponse(str(p), headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

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
    from .web_fetch_v1 import approved_rows
    surface=export_capability_surface()
    eg=approved_rows(str(DEMO_ROOT/"EGRESS.md"))
    visible=sorted({ln for row in eg.values() for ln in (row.get("lanes") or [])})
    surface["web.fetch"]={
        "permission":"read_only",
        "lanes":["fast","deep","full","research","cc"],
        "egress_visible_lanes":visible,
        "approved_domains":sorted(eg),
    }
    surface["web.search"]={
        "permission":"read_only",
        "lanes":["fast","deep","full","research","cc","scout"],
        "egress_visible_lanes":visible,
    }
    surface["mail.read"]={
        "permission":"read_only",
        "available":False,
        "lanes":["scout","research","deep"],
        "note":"IMAP read-only; not wired — Lyra supplies IMAP host + env key name",
    }
    surface["mail.send"]={
        "permission":"blocked",
        "available":False,
        "lanes":["deep"],
        "note":"born BLOCKED; per-message Lyra 放行; not wired",
    }
    return surface

class RwaConnectBody(BaseModel):
    mission_id:str
    action_id:str|None=None
    decision_origin:str
    run_id:str|None=None
    operation:str="rwa.onchain_read"

@app.get("/api/rwa/onchain")
async def rwa_onchain_published():
    from app.crypto_rwa.rwa_chain_connect import load_published
    return load_published()

@app.post("/api/rwa/onchain")
async def rwa_onchain_connect(body:RwaConnectBody):
    from app.crypto_rwa.rwa_chain_connect import connect_run
    if any(x in body.operation.lower() for x in ("transfer","send","approve","swap","trade","withdraw")):
        raise HTTPException(status_code=403,detail="money-moving methods forbidden")
    ctx={
        "mission_id":body.mission_id,
        "action_id":body.action_id or "rwa.onchain_read",
        "decision_origin":body.decision_origin,
        "operation":body.operation,
    }
    try:
        return connect_run(ctx,run_id=body.run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400,detail=str(exc)) from exc

def _request_scope(request)->str:
    return getattr(getattr(request,"state",None),"scope",None) or "full"

@app.post("/api/jobs")
async def api_create_job(body:ApiJobBody, request: Request):
    scope=_request_scope(request)
    if scope=="page":
        raise HTTPException(403,"page scope cannot post jobs")
    if body.worker not in KNOWN_WORKERS and (body.origin or "")!="grid_compiled" and not body.steps:
        job=store.create_job(channel="grid",goal=body.content,worker=body.worker,
            allowed_tools=[],allowed_paths=["."],cloud_allowed=False,
            approval_mode="write_ok_no_deploy",read_only=bool(body.read_only),
            kind=body.kind,status="blocked",last_step="UNKNOWN_WORKER")
        store.append_event(job["job_id"],"blocked",{"reason":"UNKNOWN_WORKER"})
        return {"job_id":job["job_id"],"status":job["status"],"last_step":job["last_step"]}
    worker=body.worker if body.worker in KNOWN_WORKERS else "cc"
    job=create_job_internal(JobCreate(
        channel="grid",goal=body.content,worker=worker,
        cloud_allowed=True if worker=="local" else False,
        approval_mode="auto" if body.read_only else "write_ok_no_deploy",
        read_only=bool(body.read_only),kind=body.kind,
        origin=body.origin,context_hash=body.context_hash,
        lane=body.lane,
        latency_budget_ms=body.latency_budget_ms,steps=list(body.steps or []),
    ),scope=scope)
    return {"job_id":job["job_id"],"status":job["status"],"last_step":job.get("last_step"),
            "origin":job.get("origin"),"context_hash":job.get("context_hash"),
            "read_only":job.get("read_only"),"worker":job.get("worker"),
            "topology_ack":job.get("topology_ack"),
            "receipt_event_id":job.get("receipt_event_id")}

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
        "origin":job.get("origin"),
        "context_hash":job.get("context_hash"),
        "topology_ack":job.get("topology_ack"),
        "events":store.list_events(job_id),
    }

@app.get("/api/receipts/{event_id}")
async def api_get_receipt(event_id:str):
    row=store.get_job_receipt(event_id)
    job=None
    if row:
        try: job=store.get_job(row["job_id"])
        except KeyError: job=None
    if not row:
        try:
            job=store.get_job(event_id)
        except KeyError:
            job=None
        if job:
            row=store.get_job_receipt_by_job(job["job_id"])
            if not row and job.get("receipt_event_id"):
                row=store.get_job_receipt(job["receipt_event_id"])
    if not row and not job:
        raise HTTPException(404,"receipt not found")
    jid=(row or {}).get("job_id") or (job or {}).get("job_id")
    if job is None and jid:
        try: job=store.get_job(jid)
        except KeyError: job=None
    events=store.list_events(jid) if jid else []
    output=(row or {}).get("worker_output") or worker_output_from_events(events)
    eid=(row or {}).get("event_id") or (job or {}).get("receipt_event_id") or event_id
    line=(row or {}).get("receipt_line") or provenance_line_raw(eid)
    if job and output and eid:
        store.put_job_receipt(event_id=eid,job_id=job["job_id"],receipt_line=line,worker_output=output)
    dur=duration_ms_for(jid,eid) if jid else None
    return {
        "event_id":eid,
        "job_id":jid,
        "context_hash":(job or {}).get("context_hash") or "",
        "status":(job or {}).get("status"),
        "worker":(job or {}).get("worker"),
        "topology_ack":bool((job or {}).get("topology_ack")),
        "duration_ms":dur,
        "receipt_line":line,
        "worker_output":output,
        "last_line":last_nonempty_line(output),
    }

class CompileRegister(BaseModel):
    model_config=ConfigDict(extra="forbid")
    goal:str=Field(min_length=1)
    session_id:str="default"
    owner:str=Field(min_length=4)

class CompileConfirm(BaseModel):
    model_config=ConfigDict(extra="forbid")
    candidate_id:str=Field(min_length=4)
    binding_hash:str=Field(min_length=8)
    session_id:str="default"
    owner:str=Field(min_length=4)

@app.post("/compile/register")
async def compile_register(body:CompileRegister, request:Request):
    if getattr(request.state,"scope",None) not in {"full"}:
        raise HTTPException(403,"compile adapter scope required")
    from .compile_confirm import register
    out=register(owner=body.owner, session_id=body.session_id, goal=body.goal)
    if not out.get("ok"):
        raise HTTPException(int(out.get("http") or 400), out.get("error") or "rejected")
    return out

@app.post("/compile/confirm")
async def compile_confirm(body:CompileConfirm, request:Request):
    if getattr(request.state,"scope",None) not in {"full"}:
        raise HTTPException(403,"compile adapter scope required")
    from .compile_confirm import submit
    out=submit(body.model_dump(), create_job=lambda **kw: create_job_internal(JobCreate(**kw)), owner=body.owner)
    if not out.get("ok"):
        raise HTTPException(int(out.get("http") or 400), out.get("error") or "rejected")
    return out

@app.get("/compile/map/{candidate_id}")
async def compile_map(candidate_id:str, request:Request, owner:str=""):
    if getattr(request.state,"scope",None) not in {"full"}:
        raise HTTPException(403,"compile adapter scope required")
    from .compile_confirm import lookup
    rec=lookup(candidate_id, owner=owner)
    if not rec:
        raise HTTPException(404,"not found")
    jid=rec.get("job_id")
    if jid:
        try:
            rec={**rec, **{k:store.get_job(jid).get(k) for k in ("status","last_step","last_artifact")}}
        except KeyError:
            pass
    rec.pop("goal", None)
    return rec

@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id:str):
    try: job=store.get_job(job_id)
    except KeyError: raise HTTPException(404,"job not found")
    await supervisor.cancel_job(job_id)
    return store.get_job(job_id)

@app.post("/api/missions")
async def create_mission(body:MissionCreate):
    if body.status not in {"proposed","running"}:
        raise HTTPException(400,"status must be proposed or running")
    # 衔拍3 §①1: 若未显式给 search 块,从 lane 对应模板加载结构化 catalog 查询(scout 模板)
    search_block = body.search
    if search_block is None and body.lane:
        try:
            from mission.config import mission_template
            tmpl = mission_template(body.lane)
            if tmpl and tmpl.get("search"):
                search_block = tmpl["search"]
        except Exception:
            pass
    m=store.create_mission(goal=body.goal,lane=body.lane,worker=body.worker,
                           budget_hops=body.budget_hops,budget_tokens=body.budget_tokens,
                           budget_wall_s=body.budget_wall_s,budget_usd=body.budget_usd,
                           stop_conditions=body.stop_conditions,created_by=body.created_by,
                           tools=body.tools,search=search_block)
    if body.status=="running":
        store.update_mission(m["mission_id"],status="running")
    return store.get_mission(m["mission_id"])

@app.get("/api/missions")
async def list_missions(limit:int=100,status:str|None=None):
    return store.list_missions(limit=limit,status=status)

@app.get("/api/missions/{mission_id}")
async def get_mission(mission_id:str):
    try: return store.get_mission(mission_id)
    except KeyError: raise HTTPException(404,"mission not found")

@app.post("/api/missions/{mission_id}/stop")
async def stop_mission(mission_id:str):
    try: m=store.get_mission(mission_id)
    except KeyError: raise HTTPException(404,"mission not found")
    if m["status"] in {"done","failed","rejected","stopped"}:
        return m
    store.update_mission(mission_id,status="stopped",close_reason="lyra_stop",active_job_id=None)
    return store.get_mission(mission_id)

@app.post("/api/missions/{mission_id}/approve")
async def approve_mission(mission_id:str):
    """放行: proposed → running (Lyra 页面卡)."""
    try: m=store.get_mission(mission_id)
    except KeyError: raise HTTPException(404,"mission not found")
    if m["status"]!="proposed":
        raise HTTPException(409,f"mission not proposed (status={m['status']})")
    store.update_mission(mission_id,status="running")
    return store.get_mission(mission_id)

@app.post("/api/missions/{mission_id}/reject")
async def reject_mission(mission_id:str):
    """否决: proposed → rejected, no job runs (Lyra 页面卡)."""
    try: m=store.get_mission(mission_id)
    except KeyError: raise HTTPException(404,"mission not found")
    if m["status"]!="proposed":
        raise HTTPException(409,f"mission not proposed (status={m['status']})")
    store.update_mission(mission_id,status="rejected",close_reason="lyra_reject")
    return store.get_mission(mission_id)

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
async def ws_events(ws:WebSocket,after_seq:int=0,since:int|None=None,session_id:str|None=None):
    supplied=ws.query_params.get("token","") or ws.headers.get("authorization","").removeprefix("Bearer ").strip()
    scope=resolve_scope(supplied)
    if scope is None:
        await ws.close(code=4401); return
    origin=(ws.headers.get("origin") or "").rstrip("/")
    if origin and origin!=CORS_ORIGIN and scope=="page":
        await ws.close(code=4403); return
    cursor=after_seq if since is None else int(since)
    await streamer.serve(ws,after_seq=cursor,session_id=session_id)

@app.post("/events/voice")
async def voice_event(body:VoiceEvent):
    agent_id={"local":"local-main","cc":"cc-main","fast":"fast-on-demand","deep":"deep-on-demand","full":"full-on-demand","research":"research-on-demand"}[body.target]
    s=sessions.create(agent_id,channel=body.channel,title=f"voice:{body.target}")
    msg=SessionMessage(text=body.transcript,spawn_job=True,cloud_allowed=body.cloud_allowed)
    return await session_message(s["session_id"],msg)
