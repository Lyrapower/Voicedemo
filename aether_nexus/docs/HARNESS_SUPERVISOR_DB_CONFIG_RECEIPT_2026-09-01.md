# §E.1补 supervisor.py / db.py / config.toml [core] 全文 · 2026-09-01 20:25 PDT

> 给守恒合身用。戌贴全文,禁按记忆写。三份均经敏感扫描:supervisor.py / db.py 零命中;config.toml 仅 [cc] 段有 `[REDACTED: 身份]` 路径(本回执只贴 [core],未涉)。

---

## 一、config.toml [core] 段

```toml
[core]
db_path = "./state/harness.db"
gateway_base = "http://127.0.0.1:8501"
gateway_timeout_seconds = 120
poll_interval_seconds = 1.0
max_retries = 2
max_concurrency = 4
```

---

## 二、harness/supervisor.py 全文(364 行)

```python
from __future__ import annotations
import asyncio, json, time
from typing import Any
from .config import Config
from .db import Store
from .gateway import GatewayClient
from .cc import CCExecutor
from .memory_adapter import MemoryRouter
from .context import ContextAssembler

SYSTEM="""You are a resident execution worker inside Grid.
Return useful work, not roleplay.
Never claim a tool ran unless the harness actually ran it.
If you need cloud escalation, emit exactly one JSON object:
{"action":"escalate","target":"glm|kimi","reason":"..."}
Do not invent tool results.
"""

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

            # fill concurrency slots with atomically claimed jobs
            while len(self._tasks) < self.cfg.core.max_concurrency:
                job=self.store.claim_next_queued()
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

    async def _run_job(self,job:dict[str,Any]):
        jid=job["job_id"]
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
                result=await self.cc.run(job,context_pack=context_pack)
                if result["ok"]:
                    self.store.update_job(jid,status="done",last_step="cc_done",
                                          last_artifact=result.get("job_dir"))
                    self.store.append_event(jid,"job_result",result)
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
                if not job["cloud_allowed"]:
                    self.store.update_job(jid,status="blocked",last_step="cloud_escalation_denied")
                    self.store.append_event(jid,"blocked",{"reason":"cloud escalation denied","request":esc})
                    if sess:
                        self.store.update_session(sess["session_id"],state="waiting_approval",
                                                  waiting_for=f"cloud:{esc['target']}",
                                                  last_heartbeat=time.time())
                        self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                                       kind="waiting_approval",
                                                       payload={"reason":"cloud escalation denied","request":esc})
                    return
                route=self._route_for(esc["target"])
                effective_worker=self._worker_for_route(route)
                self.store.append_event(jid,"escalated",esc)
                if sess:
                    self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                                   kind="escalated",payload=esc)
                result=await self._model_job(job,route,sess)

            self.store.update_job(jid,status="done",last_step="completed")
            self.store.append_event(jid,"job_result",{"text":result,"route":route})
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
        except Exception as e:
            cur=self.store.get_job(jid)
            rc=cur["retry_count"]
            self.store.append_event(jid,"job_exception",{"error":repr(e)})
            if sess:
                self.store.append_stream_event(session_id=sess["session_id"],job_id=jid,
                                               kind="job_exception",payload={"error":repr(e)})
            if rc < self.cfg.core.max_retries:
                self.store.update_job(jid,status="queued",retry_count=rc+1,last_step="retry_queued")
            else:
                self.store.update_job(jid,status="failed",last_step="max_retries_exceeded")
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
            return self.gateway.extract_text(resp)

        if chunks:
            return "".join(chunks)

        resp=await self.gateway.chat(route,messages)
        return self.gateway.extract_text(resp)

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

    def _worker_for_route(self,route):
        if route==self.cfg.models.local_route:
            return "qwen"
        if route==self.cfg.models.deep_route:
            return "glm"
        if route==self.cfg.models.multimodal_route:
            return "kimi"
        raise ValueError(f"unknown model route: {route}")

    def _route_for(self,w):
        if w=="qwen": return self.cfg.models.local_route
        if w=="glm": return self.cfg.models.deep_route
        if w=="kimi": return self.cfg.models.multimodal_route
        raise ValueError(f"unknown worker: {w}")

    @staticmethod
    def _parse_escalation(text):
        s=text.strip()
        if not(s.startswith("{") and s.endswith("}")): return None
        try: o=json.loads(s)
        except Exception: return None
        if o.get("action")!="escalate" or o.get("target") not in {"glm","kimi"}: return None
        return {"target":o["target"],"reason":str(o.get("reason",""))}
```

---

## 三、harness/db.py 全文(262 行)

```python
from __future__ import annotations
import json, sqlite3, threading, time, uuid
from pathlib import Path
from typing import Any

class Store:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(
              job_id TEXT PRIMARY KEY,
              channel TEXT NOT NULL,
              goal TEXT NOT NULL,
              worker TEXT NOT NULL,
              allowed_tools TEXT NOT NULL,
              allowed_paths TEXT NOT NULL,
              cloud_allowed INTEGER NOT NULL,
              approval_mode TEXT NOT NULL,
              status TEXT NOT NULL,
              retry_count INTEGER NOT NULL DEFAULT 0,
              last_step TEXT,
              last_artifact TEXT,
              pending_tool TEXT,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events(
              event_id TEXT PRIMARY KEY,
              job_id TEXT,
              kind TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at REAL NOT NULL,
              FOREIGN KEY(job_id) REFERENCES jobs(job_id)
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_events_job_created ON events(job_id,created_at);
            CREATE TABLE IF NOT EXISTS sessions(
              session_id TEXT PRIMARY KEY,
              agent_id TEXT NOT NULL,
              channel TEXT NOT NULL,
              title TEXT NOT NULL,
              state TEXT NOT NULL,
              active_job_id TEXT,
              waiting_for TEXT,
              last_heartbeat REAL,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS thread_messages(
              message_id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              created_at REAL NOT NULL,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            CREATE TABLE IF NOT EXISTS stream_events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT,
              event_id TEXT UNIQUE NOT NULL,
              session_id TEXT,
              job_id TEXT,
              kind TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_state ON sessions(state);
            CREATE INDEX IF NOT EXISTS idx_messages_session_created ON thread_messages(session_id,created_at);
            CREATE INDEX IF NOT EXISTS idx_stream_seq ON stream_events(seq);

            """)
            self._conn.commit()

    def create_job(self, *, channel, goal, worker, allowed_tools, allowed_paths, cloud_allowed, approval_mode):
        now=time.time(); job_id=f"J-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._conn.execute("""INSERT INTO jobs(
              job_id,channel,goal,worker,allowed_tools,allowed_paths,cloud_allowed,
              approval_mode,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,'queued',?,?)""",
            (job_id,channel,goal,worker,json.dumps(allowed_tools),json.dumps(allowed_paths),
             int(cloud_allowed),approval_mode,now,now))
            self._conn.commit()
        self.append_event(job_id,"job_created",{"goal":goal,"worker":worker})
        return self.get_job(job_id)

    def get_job(self, job_id):
        with self._lock:
            r=self._conn.execute("SELECT * FROM jobs WHERE job_id=?",(job_id,)).fetchone()
        if not r: raise KeyError(job_id)
        return self._decode(r)

    def list_jobs(self, limit=100):
        with self._lock:
            rows=self._conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?",(limit,)).fetchall()
        return [self._decode(r) for r in rows]

    def claim_next_queued(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            r=self._conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not r:
                self._conn.commit()
                return None
            now=time.time()
            self._conn.execute("UPDATE jobs SET status='running',updated_at=? WHERE job_id=? AND status='queued'",
                               (now,r["job_id"]))
            self._conn.commit()
        return self.get_job(r["job_id"])

    def next_queued(self):
        with self._lock:
            r=self._conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        return self._decode(r) if r else None

    def update_job(self, job_id, **fields):
        fields["updated_at"]=time.time()
        allowed={"worker","status","retry_count","last_step","last_artifact","pending_tool","cloud_allowed","updated_at"}
        bad=set(fields)-allowed
        if bad: raise ValueError(f"unsupported fields: {sorted(bad)}")
        pairs=", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {pairs} WHERE job_id=?", list(fields.values())+[job_id])
            self._conn.commit()
        return self.get_job(job_id)

    def append_event(self, job_id, kind, payload):
        eid=f"E-{uuid.uuid4().hex}"
        with self._lock:
            self._conn.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                               (eid,job_id,kind,json.dumps(payload,ensure_ascii=False),time.time()))
            self._conn.commit()
        return eid

    def list_events(self, job_id, limit=200):
        with self._lock:
            rows=self._conn.execute("SELECT * FROM events WHERE job_id=? ORDER BY created_at LIMIT ?",
                                    (job_id,limit)).fetchall()
        return [{"event_id":r["event_id"],"job_id":r["job_id"],"kind":r["kind"],
                 "payload":json.loads(r["payload"]),"created_at":r["created_at"]} for r in rows]

    def mark_running_interrupted(self):
        with self._lock:
            c=self._conn.execute("UPDATE jobs SET status='interrupted',updated_at=? WHERE status='running'",(time.time(),))
            self._conn.commit()
            return c.rowcount

    def requeue_interrupted(self, max_retries):
        with self._lock:
            rows=self._conn.execute("SELECT job_id,retry_count FROM jobs WHERE status='interrupted'").fetchall()
            n=0
            for r in rows:
                if r["retry_count"] < max_retries:
                    self._conn.execute("""UPDATE jobs SET status='queued',
                    retry_count=retry_count+1,updated_at=? WHERE job_id=?""",(time.time(),r["job_id"]))
                    n+=1
            self._conn.commit()
            return n


    def create_session(self, *, agent_id, channel="grid", title=""):
        now=time.time()
        sid=f"S-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._conn.execute("""INSERT INTO sessions(
              session_id,agent_id,channel,title,state,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?)""",(sid,agent_id,channel,title or agent_id,"idle",now,now))
            self._conn.commit()
        self.append_stream_event(session_id=sid,job_id=None,kind="session_created",
                                 payload={"agent_id":agent_id,"channel":channel,"title":title or agent_id})
        return self.get_session(sid)

    def get_session(self, session_id):
        with self._lock:
            r=self._conn.execute("SELECT * FROM sessions WHERE session_id=?",(session_id,)).fetchone()
        if not r: raise KeyError(session_id)
        return dict(r)

    def list_sessions(self, limit=100):
        with self._lock:
            rows=self._conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",(limit,)).fetchall()
        return [dict(r) for r in rows]

    def update_session(self, session_id, **fields):
        fields["updated_at"]=time.time()
        allowed={"state","active_job_id","waiting_for","last_heartbeat","title","updated_at"}
        bad=set(fields)-allowed
        if bad: raise ValueError(f"unsupported session fields: {sorted(bad)}")
        pairs=", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE sessions SET {pairs} WHERE session_id=?",list(fields.values())+[session_id])
            self._conn.commit()
        return self.get_session(session_id)

    def append_message(self, session_id, role, content):
        mid=f"M-{uuid.uuid4().hex}"
        now=time.time()
        with self._lock:
            self._conn.execute("INSERT INTO thread_messages VALUES(?,?,?,?,?)",(mid,session_id,role,content,now))
            self._conn.commit()
        self.append_stream_event(session_id=session_id,job_id=None,kind="message",
                                 payload={"message_id":mid,"role":role,"content":content})
        return {"message_id":mid,"session_id":session_id,"role":role,"content":content,"created_at":now}

    def list_messages(self, session_id, limit=500):
        with self._lock:
            rows=self._conn.execute("""SELECT * FROM thread_messages
                WHERE session_id=? ORDER BY created_at ASC LIMIT ?""",(session_id,limit)).fetchall()
        return [dict(r) for r in rows]

    def append_stream_event(self, *, session_id, job_id, kind, payload):
        eid=f"SE-{uuid.uuid4().hex}"
        now=time.time()
        with self._lock:
            cur=self._conn.execute("""INSERT INTO stream_events(
              event_id,session_id,job_id,kind,payload,created_at
            ) VALUES(?,?,?,?,?,?)""",(eid,session_id,job_id,kind,json.dumps(payload,ensure_ascii=False),now))
            seq=cur.lastrowid
            self._conn.commit()
        return {"seq":seq,"event_id":eid,"session_id":session_id,"job_id":job_id,
                "kind":kind,"payload":payload,"created_at":now}

    def list_stream_events(self, after_seq=0, limit=1000, session_id=None):
        sql="SELECT * FROM stream_events WHERE seq>?"
        args=[after_seq]
        if session_id:
            sql+=" AND session_id=?"
            args.append(session_id)
        sql+=" ORDER BY seq ASC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows=self._conn.execute(sql,args).fetchall()
        return [{"seq":r["seq"],"event_id":r["event_id"],"session_id":r["session_id"],
                 "job_id":r["job_id"],"kind":r["kind"],"payload":json.loads(r["payload"]),
                 "created_at":r["created_at"]} for r in rows]

    def find_session_by_job(self, job_id):
        with self._lock:
            r=self._conn.execute("SELECT * FROM sessions WHERE active_job_id=?",(job_id,)).fetchone()
        return dict(r) if r else None

    def bind_job_to_session(self, session_id, job_id):
        self.update_session(session_id,state="running",active_job_id=job_id,waiting_for=None)
        self.append_stream_event(session_id=session_id,job_id=job_id,kind="job_bound",
                                 payload={"job_id":job_id})

    @staticmethod
    def _decode(r):
        return {
          "job_id":r["job_id"],"channel":r["channel"],"goal":r["goal"],"worker":r["worker"],
          "allowed_tools":json.loads(r["allowed_tools"]),"allowed_paths":json.loads(r["allowed_paths"]),
          "cloud_allowed":bool(r["cloud_allowed"]),"approval_mode":r["approval_mode"],
          "status":r["status"],"retry_count":r["retry_count"],"last_step":r["last_step"],
          "last_artifact":r["last_artifact"],"pending_tool":r["pending_tool"],
          "created_at":r["created_at"],"updated_at":r["updated_at"]
        }
```

---

—— 戌,2026-09-01 PDT
