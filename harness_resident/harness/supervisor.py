from __future__ import annotations
import asyncio, json, os, time
from pathlib import Path
from typing import Any
from .envutil import ensure_demo_on_path
ensure_demo_on_path()
from .config import Config
from .db import Store
from .gateway import GatewayClient, ModelMismatch
from .cc import CCExecutor
from .memory_adapter import MemoryRouter
from .context import ContextAssembler

SYSTEM="""You are a resident execution worker inside Grid.
Return useful work, not roleplay.
Never claim a tool ran unless the harness actually ran it.
If you need cloud escalation, emit exactly one JSON object:
{"action":"escalate","target":"glm","reason":"..."}
Do not invent tool results.
"""

_WORKER_RESOURCE={
    "local":"harness.local_lane",
    "cc":"harness.cc_lane",
    "fast":"harness.cloud_lane",
    "deep":"harness.cloud_lane",
    "full":"harness.cloud_lane",
    "research":"harness.cloud_lane",
}

class Supervisor:
    def __init__(self,cfg:Config,store:Store):
        self.cfg=cfg
        self.store=store
        self.gateway=GatewayClient(cfg)
        self.cc=CCExecutor(cfg)
        self.memories=MemoryRouter(cfg)
        self.context=ContextAssembler(cfg,store,self.memories)
        self._stop=asyncio.Event()
        self._tasks:dict[str,asyncio.Task]={}
        self._isolated=os.getenv("GRID_SCHED_ISOLATED","").strip().lower() in {"1","true","yes"}
        if self._isolated:
            db=Path(self.cfg.core.db_path).resolve()
            prod=(Path(__file__).resolve().parents[1]/"state"/"harness.db").resolve()
            if db==prod:
                raise RuntimeError("GRID_SCHED_ISOLATED refuses production harness.db")
        self._assert_no_aster()

    def _assert_no_aster(self):
        routes=[
            self.cfg.models.local_route,self.cfg.models.fast_route,
            self.cfg.models.deep_route,self.cfg.models.full_route,
            self.cfg.models.research_route,
        ]
        if any(str(r)=="demo/aster" or str(r).startswith("demo/aster") for r in routes):
            raise RuntimeError("demo/aster is not a harness lane")

    async def startup_recovery(self):
        n=self.store.mark_running_interrupted()
        if n:
            self.store.append_event(None,"recovery_interrupted",{"count":n})
        if self.cfg.policy.auto_resume_interrupted:
            q=self.store.requeue_interrupted(self.cfg.core.max_retries)
            if q:
                self.store.append_event(None,"recovery_requeued",{"count":q})

    async def run_forever(self):
        await self.startup_recovery()
        while not self._stop.is_set():
            # reap completed tasks
            dead=[jid for jid,t in self._tasks.items() if t.done()]
            for jid in dead:
                t=self._tasks.pop(jid)
                try: t.result()
                except asyncio.CancelledError: pass
                except Exception as e:
                    self.store.append_event(jid,"supervisor_task_error",{"error":repr(e)})

            # active task heartbeat: connection may be quiet while work is still alive
            for jid,t in list(self._tasks.items()):
                if not t.done():
                    sess=self.store.find_session_by_job(jid)
                    if sess:
                        self.store.update_session(sess["session_id"],last_heartbeat=time.time())

            try:
                from .task_schedule import enqueue_due
                def _sched_create(**kw):
                    keys=("channel","goal","worker","allowed_tools","allowed_paths",
                          "cloud_allowed","approval_mode","read_only","kind","origin","context_hash")
                    return self.store.create_job(**{k:kw[k] for k in keys if k in kw})
                enqueue_due(
                    create_job=_sched_create,
                    origin="isolated_sched" if self._isolated else "",
                )
            except Exception:
                pass

            # fill concurrency slots with atomically claimed jobs
            while len(self._tasks) < self.cfg.core.max_concurrency:
                job=self.store.claim_next_queued(isolated=self._isolated)
                if not job: break
                task=asyncio.create_task(self._run_job(job),name=f"job:{job['job_id']}")
                self._tasks[job["job_id"]]=task

            await asyncio.sleep(self.cfg.core.poll_interval_seconds)

    async def stop(self):
        self._stop.set()
        for t in list(self._tasks.values()):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(),return_exceptions=True)
        await self.gateway.close()
        await self.memories.close()

    async def cancel_job(self,job_id:str):
        t=self._tasks.get(job_id)
        if t:
            t.cancel()
        try:
            self.store.update_job(job_id,status="interrupted",last_step="cancelled")
        except KeyError:
            pass
        try:
            names=self.cc._names(job_id)
            self.cc._cleanup_job(names, remove_volumes=False)
        except Exception:
            pass

    async def _run_with_cancel_watch(self,jid:str,coro):
        """Run coro; if another process (API) flips job status to interrupted,
        cancel the task so _run_docker's finally cleans up containers.
        Closes the orphan-container race when cancel lands during dispatch."""
        main=asyncio.ensure_future(coro)
        async def _watch():
            while not main.done():
                try:
                    st=self.store.get_job(jid).get("status")
                except KeyError:
                    st="interrupted"
                if st=="interrupted":
                    main.cancel()
                    return
                await asyncio.sleep(2.0)
        watcher=asyncio.ensure_future(_watch())
        try:
            return await main
        finally:
            watcher.cancel()
            try: await watcher
            except asyncio.CancelledError: pass

    async def pause_session(self,session_id:str):
        s=self.store.get_session(session_id)
        jid=s.get("active_job_id")
        if jid and jid in self._tasks:
            self._tasks[jid].cancel()
        if jid:
            try: self.store.update_job(jid,status="interrupted",last_step="paused_by_user")
            except KeyError: pass
        ss=self.store.update_session(session_id,state="paused",last_heartbeat=time.time())
        self.store.append_stream_event(session_id=session_id,job_id=jid,kind="session_state",
                                       payload={"state":"paused"})
        return ss

    async def resume_session(self,session_id:str):
        s=self.store.get_session(session_id)
        jid=s.get("active_job_id")
        if jid:
            try:
                j=self.store.get_job(jid)
                if j["status"] in {"interrupted","blocked","failed"}:
                    self.store.update_job(jid,status="queued",last_step="resumed_by_user")
                    ss=self.store.update_session(session_id,state="running",last_heartbeat=time.time())
                else:
                    ss=self.store.update_session(session_id,state="running",last_heartbeat=time.time())
            except KeyError:
                ss=self.store.update_session(session_id,state="idle",active_job_id=None,last_heartbeat=time.time())
        else:
            ss=self.store.update_session(session_id,state="idle",last_heartbeat=time.time())
        self.store.append_stream_event(session_id=session_id,job_id=jid,kind="session_state",
                                       payload={"state":ss["state"]})
        return ss

    async def cancel_session(self,session_id:str):
        s=self.store.get_session(session_id)
        jid=s.get("active_job_id")
        if jid and jid in self._tasks:
            self._tasks[jid].cancel()
        if jid:
            try: self.store.update_job(jid,status="cancelled",last_step="cancelled_by_user")
            except KeyError: pass
        ss=self.store.update_session(session_id,state="cancelled",active_job_id=None,
                                     waiting_for=None,last_heartbeat=time.time())
        self.store.append_stream_event(session_id=session_id,job_id=jid,kind="session_state",
                                       payload={"state":"cancelled"})
        return ss

    async def approve_session(self,session_id:str,note="approved"):
        s=self.store.get_session(session_id)
        jid=s.get("active_job_id")
        if jid:
            try:
                j=self.store.get_job(jid)
                if j["status"]=="blocked":
                    self.store.update_job(jid,status="queued",cloud_allowed=1,last_step="approved_requeue")
            except KeyError: pass
        ss=self.store.update_session(session_id,state="running",waiting_for=None,last_heartbeat=time.time())
        self.store.append_stream_event(session_id=session_id,job_id=jid,kind="approval",
                                       payload={"decision":"approve","note":note})
        return ss

    async def reject_session(self,session_id:str,note="rejected"):
        s=self.store.get_session(session_id)
        jid=s.get("active_job_id")
        if jid:
            try: self.store.update_job(jid,status="cancelled",last_step="rejected_by_user")
            except KeyError: pass
        ss=self.store.update_session(session_id,state="blocked",waiting_for=None,last_heartbeat=time.time())
        self.store.append_stream_event(session_id=session_id,job_id=jid,kind="approval",
                                       payload={"decision":"reject","note":note})
        return ss

    def _scope_for(self,job:dict[str,Any])->str:
        if job.get("kind")=="money_moving":
            return "money_moving"
        if job.get("read_only",True):
            return "read_only"
        return "local_write"

    def _gate_job(self,job:dict[str,Any],*,operation:str="job.run",resource:str|None=None):
        from app.harness.action_envelope import ActionEnvelope
        from app.harness.resource_gate import gate
        jid=job["job_id"]
        res=resource or _WORKER_RESOURCE.get(job["worker"])
        if not res:
            from app.harness.action_envelope import FactualReceipt
            from app.harness.provenance import record_receipt
            rc=FactualReceipt(mission_id=jid,action_id=f"{jid}:run",status="DENIED",
                              executed=False,error="UNKNOWN_WORKER",
                              metadata={"worker":job["worker"]})
            record_receipt(rc)
            return type("D",(),{"allowed":False,"reason":"UNKNOWN_WORKER","receipt":rc})()
        env=ActionEnvelope(
            mission_id=jid,
            action_id=f"{jid}:{operation}",
            decision_origin="USER",
            selected_resource=res,
            operation=operation,
            authorization_scope=self._scope_for(job),
            arguments={"worker":job["worker"],"kind":job.get("kind","chat")},
        )
        return gate(env)

    def _record_job_receipt(self,job:dict[str,Any],*,status:str,executed:bool,error:str="",
                            metadata:dict|None=None):
        from app.harness.action_envelope import FactualReceipt
        from app.harness.provenance import record_receipt
        jid=job["job_id"]
        meta=dict(metadata or {})
        meta.setdefault("job_id",jid)
        ev=record_receipt(FactualReceipt(
            mission_id=jid,action_id=f"{jid}:run",status=status,
            executed=executed,error=error,metadata=meta,
        ))
        self.store.update_job(jid,receipt_event_id=ev.get("event_id") or ev.get("event_hash"))
        return ev

    async def _run_job(self,job:dict[str,Any]):
        jid=job["job_id"]
        decision=self._gate_job(job)
        if not decision.allowed:
            self.store.update_job(jid,status="blocked",last_step="GATE_DENIED")
            self.store.append_event(jid,"blocked",{"reason":decision.reason or "GATE_DENIED"})
            return
        sess=self.store.find_session_by_job(jid)
        self.store.update_job(jid,status="running",last_step="dispatch")
        self.store.append_event(jid,"job_started",{"worker":job["worker"]})
        if sess:
            self.store.update_session(sess["session_id"],state="running",last_heartbeat=time.time())
            self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,kind="job_started",
                                           payload={"worker":job["worker"],"goal":job["goal"]})
        try:
            if job["worker"]=="cc":
                context_pack=await self.context.build(
                    worker="cc",
                    session_id=sess["session_id"] if sess else None,
                    current_turn=job["goal"],
                    job=job,
                )
                self._emit_context_receipt(sess,job,context_pack)
                result=await self._run_with_cancel_watch(jid,self.cc.run(job,context_pack=context_pack))
                try:
                    curst=self.store.get_job(jid).get("status")
                except KeyError:
                    curst=""
                if curst in {"interrupted","cancelled"}:
                    self.store.append_event(jid,"job_cancelled_runtime",{"after_cc":True,"ok":result.get("ok")})
                    return
                if result.get("blocked")=="sandbox_missing" or str(result.get("error") or "")=="BLOCKED_SANDBOX_MISSING":
                    self.store.update_job(jid,status="blocked",last_step="BLOCKED_SANDBOX_MISSING")
                    self.store.append_event(jid,"job_blocked",result)
                    self._record_job_receipt(job,status="DENIED",executed=False,
                                             error="BLOCKED_SANDBOX_MISSING",
                                             metadata={"route_id":"cc","route_class":"cc",
                                                       "sandbox":result.get("sandbox") or "missing"})
                    if sess:
                        self.store.update_session(sess["session_id"],state="blocked",last_heartbeat=time.time())
                        self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                                       kind="job_blocked",payload=result)
                    return
                if result["ok"]:
                    self.store.update_job(jid,status="done",last_step="cc_done",
                                          last_artifact=result.get("job_dir"))
                    self.store.append_event(jid,"job_result",result)
                    meta={
                        "route_id":"cc","route_class":"cc",
                        "model_requested":getattr(self.cfg.cc,"model",""),
                        "model_resolved":getattr(self.cfg.cc,"model",""),
                        "transport_locality":"127.0.0.1:11434",
                        "model_execution_locality":"derived_from_selected_model",
                    }
                    if result.get("sandbox"):
                        meta["sandbox"]=result.get("sandbox")
                    if result.get("container"):
                        meta["container"]=result.get("container")
                    self._record_job_receipt(job,status="EXECUTED",executed=True,metadata=meta)
                    if sess:
                        text=result.get("result","")
                        if text:
                            self.store.append_message(sess["session_id"],"assistant",text)
                            await self.persist_external_turn(
                                worker="cc",
                                session_id=sess["session_id"],
                                role="assistant",
                                content=text,
                                source_surface=sess.get("channel") or "grid",
                            )
                        self.store.update_session(sess["session_id"],state="idle",active_job_id=None,
                                                  last_heartbeat=time.time())
                        self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                                       kind="job_done",payload={"worker":"cc","ok":True})
                else:
                    self.store.update_job(jid,status="failed",last_step="cc_failed")
                    self.store.append_event(jid,"job_failed",result)
                    self._record_job_receipt(job,status="FAILED",executed=False,
                                             error=str(result.get("error") or "cc_failed"),
                                             metadata={"route_id":"cc","route_class":"cc",
                                                       "transport_locality":"127.0.0.1:11434",
                                                       "model_execution_locality":"derived_from_selected_model"})
                    if sess:
                        self.store.update_session(sess["session_id"],state="failed",last_heartbeat=time.time())
                        self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                                       kind="job_failed",payload=result)
                return

            route=self._route_for(job["worker"])
            effective_worker=self._worker_for_route(route)
            result=await self._model_job(job,route,sess)

            esc=self._parse_escalation(result)
            if esc:
                esc_decision=self._gate_job(job,operation="escalate",resource="harness.escalate")
                if not esc_decision.allowed or not job["cloud_allowed"]:
                    self.store.update_job(jid,status="blocked",last_step="GATE_DENIED")
                    self.store.append_event(jid,"blocked",{"reason":"cloud escalation denied","request":esc})
                    if sess:
                        self.store.update_session(sess["session_id"],state="waiting_approval",
                                                  waiting_for=f"cloud:{esc['target']}",
                                                  last_heartbeat=time.time())
                        self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                                       kind="waiting_approval",
                                                       payload={"reason":"cloud escalation denied","request":esc})
                    return
                route=self._route_for("glm")
                effective_worker=self._worker_for_route(route)
                self.store.append_event(jid,"escalated",esc)
                if sess:
                    self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                                   kind="escalated",payload=esc)
                result=await self._model_job(job,route,sess)

            if self._research_needs_web(job):
                sr=getattr(self,"_last_search",None) or {}
                if not sr:
                    self.store.update_job(jid,status="blocked",last_step="BLOCKED_NO_TOOL_EVIDENCE")
                    self.store.append_event(jid,"job_blocked",{"reason":"research requires web.search"})
                    return
                if sr.get("discovery_class")=="catalog_or_listing":
                    pass
                elif sr.get("discovery_class")=="INSUFFICIENT_DISCOVERY":
                    self.store.update_job(jid,status="blocked",last_step="INSUFFICIENT_DISCOVERY")
                    self.store.append_event(jid,"job_blocked",{"reason":"encyclopedia_or_instant_only","search":{
                        "status":sr.get("status"),"n":len(sr.get("results") or []),
                        "catalog_fetches":sr.get("catalog_fetches") or []}})
                    return
                elif not sr.get("ok") and sr.get("status") in {"SEARCH_CHALLENGE","DENIED","SEARCH_ERROR"}:
                    self.store.update_job(jid,status="blocked",last_step="BLOCKED_SEARCH")
                    self.store.append_event(jid,"job_blocked",{"reason":sr.get("status"),"attempts":sr.get("queries")})
                    return
            self.store.update_job(jid,status="done",last_step="completed")
            self.store.append_event(jid,"job_result",{"text":result,"route":route,"search":getattr(self,"_last_search",None)})
            self._record_job_receipt(job,status="EXECUTED",executed=True,metadata={
                "route_id":route,
                "route_class":"local" if "/" in str(route) else "cloud",
                "model_requested":route,
                "model_resolved":getattr(self,"_last_model_resolved",None) or route,
                "transport_locality":"127.0.0.1:8501",
                "model_execution_locality":"local" if effective_worker=="local" else "remote",
            })
            if sess:
                self.store.append_message(sess["session_id"],"assistant",result)
                await self.persist_external_turn(
                    worker=effective_worker,
                    session_id=sess["session_id"],
                    role="assistant",
                    content=result,
                    source_surface=sess.get("channel") or "grid",
                )
                self.store.update_session(sess["session_id"],state="idle",active_job_id=None,
                                          last_heartbeat=time.time())
                self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                               kind="job_done",payload={"route":route,"text":result})
        except asyncio.CancelledError:
            # user pause/cancel path already writes state; do not overwrite it
            self.store.append_event(jid,"job_cancelled_runtime",{})
            raise
        except ModelMismatch as e:
            self.store.update_job(jid,status="failed",last_step="MODEL_MISMATCH")
            self.store.append_event(jid,"job_failed",{"error":repr(e)})
            self._record_job_receipt(job,status="FAILED",executed=False,error=str(e),
                                     metadata={"route_class":"mismatch"})
            if sess:
                self.store.update_session(sess["session_id"],state="failed",last_heartbeat=time.time())
        except Exception as e:
            cur=self.store.get_job(jid)
            rc=cur["retry_count"]
            self.store.append_event(jid,"job_exception",{"error":repr(e)})
            if sess:
                self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                               kind="job_exception",payload={"error":repr(e)})
            if job.get("worker")=="cc" or job.get("kind")=="money_moving" or not job.get("read_only",True):
                self.store.update_job(jid,status="blocked",last_step="RETRY_DENIED")
                self._record_job_receipt(job,status="FAILED",executed=False,error=repr(e))
                if sess:
                    self.store.update_session(sess["session_id"],state="blocked",last_heartbeat=time.time())
            elif rc < self.cfg.core.max_retries:
                self.store.update_job(jid,status="queued",retry_count=rc+1,last_step="retry_queued")
            else:
                self.store.update_job(jid,status="failed",last_step="RETRY_EXHAUSTED")
                self._record_job_receipt(job,status="FAILED",executed=False,error=repr(e))
                if sess:
                    self.store.update_session(sess["session_id"],state="failed",last_heartbeat=time.time())

    async def _model_job(self,job,route,sess):
        worker=self._worker_for_route(route)

        pack=await self.context.build(
            worker=worker,
            session_id=sess["session_id"] if sess else None,
            current_turn=job["goal"],
            job=job,
        )
        self._emit_context_receipt(sess,job,pack)
        messages=pack.to_messages(SYSTEM)
        messages=self._merge_telegram_store(job,messages)

        text=await self._chat_collect(job,route,sess,messages)
        text=await self._web_research_loop(job,route,worker,sess,messages,text)
        text=await self._web_fetch_loop(job,route,worker,sess,messages,text)
        return text

    async def _chat_collect(self,job,route,sess,messages):
        chunks=[]
        try:
            async for piece in self.gateway.chat_stream(route,messages):
                chunks.append(piece)
                if sess:
                    self.store.update_session(sess["session_id"],last_heartbeat=time.time())
                    self.store.append_stream_event(
                        session_id=sess["session_id"],
                        job_id=job["job_id"],
                        kind="agent_delta",
                        payload={"text":piece,"route":route}
                    )
        except Exception:
            if chunks:
                raise
            resp=await self.gateway.chat(route,messages)
            self._last_model_resolved=resp.get("model") or route
            return self.gateway.extract_text(resp)

        if chunks:
            self._last_model_resolved=route
            return "".join(chunks)

        resp=await self.gateway.chat(route,messages)
        self._last_model_resolved=resp.get("model") or route
        return self.gateway.extract_text(resp)

    def _research_needs_web(self,job)->bool:
        if job.get("worker")!="research":
            return False
        g=str(job.get("goal") or "").lower()
        return any(k in g for k in ("search","grant","rfp","scout","opportunit","dossier","rwa","knowledge","gardener","prototype"))

    async def _web_research_loop(self,job,route,worker,sess,messages,text):
        # 衔拍3 §①4: 工具环按 allowed_tools 开,不按 worker 名。deep 只要 allowed_tools 含
        # web.search / grants.catalog 即开研究环——scout→deep 的设定才成立。
        allowed = job.get("allowed_tools") or []
        if not any(t in allowed for t in ("web.search", "grants.catalog", "grants.catalog_post")):
            return text
        os.environ.setdefault("WEB_FETCH_SEARCH_PROVIDERS","github,ddg_api,wikipedia,ddg_html,ddg_lite")
        from .tool_loop import (
            classify_discovery, collect_search_queries, format_search_result,
            format_tool_result, qualify_fetch, run_fetches, run_search, PROVIDER_KIND,
            SCOUT_CATALOG_URLS, catalog_hits_from_fetch, catalog_follow_urls,
            run_grants_catalog, run_grants_catalog_structured,
        )
        db_path=str(self.cfg.core.db_path)
        if not Path(db_path).is_absolute():
            db_path=str((Path(__file__).resolve().parents[1]/db_path).resolve())
        packed=collect_search_queries(str(job.get("goal") or ""), text)
        queries=packed.get("queries") or []
        g=str(job.get("goal") or "").lower()
        # lane comes from the job (mission.lane or ops-table default); fall back to goal-derivation
        # only for legacy jobs that carry no lane. goal text never overrides an explicit job.lane.
        lane=job.get("lane") or ("scout" if any(k in g for k in ("grant","rfp","scout","opportunit","procurement")) else worker)
        sr=run_search(queries,lane=lane,db_path=db_path,route_id=str(route),
                      mission_id=str(job.get("job_id") or ""))
        for r in sr.get("results") or []:
            r.setdefault("provider_kind", PROVIDER_KIND.get(str(r.get("provider") or ""), "unknown"))
        if lane=="scout":
            # 衔拍3 §①1: 结构化 catalog 从 job.search 块组请求(不从 goal 文本);同 query mission 内缓存。
            sblk = job.get("search")
            if sblk and isinstance(sblk, dict) and sblk.get("keywords"):
                cat_api = run_grants_catalog_structured(
                    sblk, lane=lane, db_path=db_path,
                    route_id=str(route), mission_id=str(job.get("job_id") or ""))
            else:
                cat_api = run_grants_catalog(
                    str(job.get("goal") or ""), lane=lane, db_path=db_path,
                    route_id=str(route), mission_id=str(job.get("job_id") or ""))
            sr["catalog"]=cat_api
            for row in cat_api.get("rows") or []:
                sr.setdefault("results", []).append({
                    "provider": "grants_gov_api",
                    "provider_kind": "catalog_discovery",
                    "title": row.get("title"),
                    "url": row.get("human_url") or row.get("detail_locator"),
                    "snippet": (
                        f"opportunity number {row.get('opportunity_number')} "
                        f"id {row.get('opportunity_id')} closing {row.get('deadline')} "
                        f"eligibility: {row.get('eligibility')} status {row.get('status')} "
                        f"qualification {row.get('qualification')}"
                    ),
                    "opportunity_id": row.get("opportunity_id"),
                    "opportunity_number": row.get("opportunity_number"),
                    "deadline": row.get("deadline"),
                    "summary": row.get("summary"),
                })
            cat=[qualify_fetch(x) for x in run_fetches(
                list(SCOUT_CATALOG_URLS),lane=lane,db_path=db_path,
                route_id=str(route),mission_id=str(job.get("job_id") or ""))]
            extra=[]
            follow=[]
            for fr in cat:
                extra.extend(catalog_hits_from_fetch(fr))
                follow.extend(catalog_follow_urls(str(fr.get("text") or "")))
            more_urls=[u for u in follow if u not in SCOUT_CATALOG_URLS][:3]
            if more_urls:
                more=[qualify_fetch(x) for x in run_fetches(
                    more_urls,lane=lane,db_path=db_path,
                    route_id=str(route),mission_id=str(job.get("job_id") or ""))]
                cat.extend(more)
                for fr in more:
                    extra.extend(catalog_hits_from_fetch(fr))
            if extra:
                sr.setdefault("results", []).extend(extra)
                sr["catalog_fetches"]=[{"url":x.get("source_url"),"status":x.get("status"),
                                       "ok":x.get("ok"),"chars":x.get("chars")} for x in cat]
        sr["discovery_class"]=classify_discovery(sr.get("results") or [], lane=lane)
        sr["rewrites"]=packed.get("rewrites") or []
        self._last_search=sr
        self.store.append_event(job["job_id"],"tool_search",{
            "queries":queries,"rewrites":sr["rewrites"],"status":sr.get("status"),
            "ok":sr.get("ok"),"retryable":sr.get("retryable"),
            "n":len(sr.get("results") or []),"discovery_class":sr["discovery_class"],
            "lane":lane,"attempts":sr.get("queries"),
            "catalog_fetches":sr.get("catalog_fetches") or [],
            # 衔拍3 §①3: catalog rows 进 event,runner 据此自动附 URL/截止/event_id 建 findings。
            "catalog_rows":[
                {"opportunity_id":r.get("opportunity_id"),"title":r.get("title"),
                 "publisher":r.get("publisher"),"deadline":r.get("deadline"),
                 "human_url":r.get("human_url"),"status":r.get("status"),
                 "summary":(r.get("summary") or "")[:200]}
                for r in (sr.get("catalog",{}) or {}).get("rows",[])
            ],
        })
        blob=format_search_result(sr)
        budget=int(job.get("fetch_budget") or 4)
        urls=[r.get("url") for r in (sr.get("results") or []) if str(r.get("url") or "").startswith("https://")]
        fetched=[]
        if urls:
            fetched=[qualify_fetch(x) for x in run_fetches(
                urls[:budget],lane=lane,db_path=db_path,route_id=str(route),
                mission_id=str(job.get("job_id") or ""))]
            self.store.append_event(job["job_id"],"tool_fetch",{
                "urls":urls[:budget],"n":len(fetched),
                "statuses":[x.get("status") for x in fetched],
            })
            blob+="\n"+ "\n".join(format_tool_result(r) for r in fetched)
        if sr.get("discovery_class")=="INSUFFICIENT_DISCOVERY":
            blob+="\nDISCOVERY=INSUFFICIENT_DISCOVERY. Do not write no qualifying opportunities. Report insufficient discovery and unknown eligibility fields."
        messages=list(messages)+[
            {"role":"assistant","content":text},
            {"role":"user","content":"工具回注(web.search/web.fetch):\n"+blob+
             "\n用以上结果作答。具体条目才能 qualified/rejected/needs_verification。百科/即时答案不够。不要只说先搜 store。"},
        ]
        return await self._chat_collect(job,route,sess,messages)

    async def _web_fetch_loop(self,job,route,worker,sess,messages,text):
        from .tool_loop import MAX_FETCH_ROUNDS, collect_fetch_urls, format_tool_result, run_fetches
        db_path=str(self.cfg.core.db_path)
        if not Path(db_path).is_absolute():
            db_path=str((Path(__file__).resolve().parents[1]/db_path).resolve())
        goal=str(job.get("goal") or "")
        seen=set()
        for _ in range(MAX_FETCH_ROUNDS):
            urls=[u for u in collect_fetch_urls(goal,text) if u not in seen]
            if not urls:
                return text
            for u in urls:
                seen.add(u)
            results=run_fetches(
                urls,lane=job.get("lane") or worker,db_path=db_path,
                route_id=str(route),mission_id=str(job.get("job_id") or ""),
            )
            blob="\n".join(format_tool_result(r) for r in results)
            self.store.append_event(job["job_id"],"tool_fetch",{"urls":urls,"n":len(results)})
            messages=list(messages)+[
                {"role":"assistant","content":text},
                {"role":"user","content":"工具回注(web.fetch):\n"+blob+"\n用以上结果继续作答。"},
            ]
            text=await self._chat_collect(job,route,sess,messages)
        return text

    def _emit_context_receipt(self,sess,job,pack):
        if not self.cfg.memory.emit_context_receipts:
            return
        receipt=pack.receipt()
        self.store.append_event(job["job_id"],"context_receipt",receipt)
        if sess:
            self.store.append_stream_event(
                session_id=sess["session_id"],
                job_id=job["job_id"],
                kind="context_receipt",
                payload=receipt,
            )

    async def persist_external_turn(
        self,
        *,
        worker:str,
        session_id:str,
        role:str,
        content:str,
        source_surface:str,
    ):
        # persist: write_mode=gateway_owned → attempted=False; harness worker domain only.
        # never diary / Memory Palace (those writes are closed).
        domain=self.memories.for_worker(worker)
        result=await domain.write_turn(
            session_id=session_id,
            role=role,
            content=content,
            source_surface=source_surface,
            worker=worker,
        )
        if result.get("attempted"):
            self.store.append_stream_event(
                session_id=session_id,
                job_id=None,
                kind="memory_write_receipt",
                payload=result,
            )
        return result

    async def preview_context(self,*,worker:str,session_id:str,current_turn:str):
        query=current_turn
        if not query:
            history=self.store.list_messages(session_id,limit=100)
            for m in reversed(history):
                if m.get("role")=="user" and m.get("content"):
                    query=m["content"]
                    break
        return await self.context.build(
            worker=worker,
            session_id=session_id,
            current_turn=query,
            job=None,
        )

    def _merge_telegram_store(self,job,messages):
        """Telegram jobs: prepend 8501 store turns so lane memory is the source of truth."""
        ch=str(job.get("channel") or "")
        if not ch.startswith("telegram-"):
            return messages
        lane=ch.removeprefix("telegram-")
        from .telegram_channels import LANES
        spec=LANES.get(lane)
        if not spec:
            return messages
        try:
            from . import store_memory
            rows=store_memory.get_messages(spec["store"], limit=40)
            hist=store_memory.as_chat_messages(rows, drop_trailing_user=job.get("goal"))
        except Exception:
            return messages
        if not hist:
            return messages
        sys0=[m for m in messages if m.get("role")=="system"][:1]
        rest=[m for m in messages if m.get("role")!="system"]
        return sys0+hist+rest

    def _worker_for_route(self,route):
        if route==self.cfg.models.local_route:
            return "local"
        if route==self.cfg.models.fast_route:
            return "fast"
        if route==self.cfg.models.deep_route:
            return "deep"
        if route==self.cfg.models.full_route:
            return "full"
        if route==self.cfg.models.research_route:
            return "research"
        raise ValueError(f"unknown model route: {route}")

    def _route_for(self,w):
        if w=="local": return self.cfg.models.local_route
        if w=="fast": return self.cfg.models.fast_route
        if w=="deep": return self.cfg.models.deep_route
        if w=="full": return self.cfg.models.full_route
        if w=="research": return self.cfg.models.research_route
        if w=="glm": return self.cfg.models.deep_route
        raise ValueError(f"unknown worker: {w}")

    @staticmethod
    def _parse_escalation(text):
        s=text.strip()
        if not(s.startswith("{") and s.endswith("}")): return None
        try: o=json.loads(s)
        except Exception: return None
        if o.get("action")!="escalate" or o.get("target") not in {"glm"}: return None
        return {"target":o["target"],"reason":str(o.get("reason",""))}
