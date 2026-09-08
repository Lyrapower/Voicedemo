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
            CREATE TABLE IF NOT EXISTS job_receipts(
              event_id TEXT PRIMARY KEY,
              job_id TEXT,
              receipt_line TEXT NOT NULL,
              worker_output TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_job_receipts_job ON job_receipts(job_id);
            CREATE TABLE IF NOT EXISTS missions(
              mission_id TEXT PRIMARY KEY,
              goal TEXT NOT NULL,
              lane TEXT NOT NULL,
              worker TEXT NOT NULL,
              budget_hops INTEGER NOT NULL DEFAULT 0,
              budget_tokens INTEGER NOT NULL DEFAULT 0,
              budget_wall_s REAL NOT NULL DEFAULT 0,
              budget_usd REAL NOT NULL DEFAULT 0,
              stop_conditions TEXT NOT NULL DEFAULT '[]',
              status TEXT NOT NULL DEFAULT 'proposed',
              created_by TEXT NOT NULL DEFAULT '',
              lineage_root_event_id TEXT,
              hops_used INTEGER NOT NULL DEFAULT 0,
              usd_used REAL NOT NULL DEFAULT 0,
              tokens_used INTEGER NOT NULL DEFAULT 0,
              denied_streak INTEGER NOT NULL DEFAULT 0,
              out_of_bounds INTEGER NOT NULL DEFAULT 0,
              active_job_id TEXT,
              dossier_path TEXT,
              close_reason TEXT,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status);
            """)
            self._conn.commit()
            self._migrate_jobs()

    def _migrate_jobs(self):
        cols={r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}
        if "read_only" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN read_only INTEGER NOT NULL DEFAULT 1")
        if "kind" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'")
        if "receipt_event_id" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN receipt_event_id TEXT")
        if "origin" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN origin TEXT NOT NULL DEFAULT ''")
        if "context_hash" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN context_hash TEXT NOT NULL DEFAULT ''")
        if "latency_budget_ms" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN latency_budget_ms INTEGER")
        if "steps" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN steps TEXT NOT NULL DEFAULT '[]'")
        if "topology_ack" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN topology_ack INTEGER NOT NULL DEFAULT 0")
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_confirm_hash "
            "ON jobs(context_hash) WHERE origin='grid_c_confirm' AND IFNULL(context_hash,'')!=''"
        )
        self._conn.commit()

    def create_job(self, *, channel, goal, worker, allowed_tools, allowed_paths, cloud_allowed, approval_mode,
                   read_only=True, kind="chat", status="queued", last_step=None,
                   origin="", context_hash="", latency_budget_ms=None, steps=None, topology_ack=False):
        now=time.time()
        origin=origin or ""
        context_hash=context_hash or ""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            if origin=="grid_c_confirm" and context_hash:
                r=self._conn.execute(
                    "SELECT job_id FROM jobs WHERE origin='grid_c_confirm' AND context_hash=?",
                    (context_hash,)).fetchone()
                if r:
                    self._conn.commit()
                    return self.get_job(r["job_id"])
            job_id=f"J-{uuid.uuid4().hex[:12]}"
            try:
                self._conn.execute("""INSERT INTO jobs(
                  job_id,channel,goal,worker,allowed_tools,allowed_paths,cloud_allowed,
                  approval_mode,status,created_at,updated_at,read_only,kind,last_step,
                  origin,context_hash,latency_budget_ms,steps,topology_ack
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id,channel,goal,worker,json.dumps(allowed_tools),json.dumps(allowed_paths),
                 int(cloud_allowed),approval_mode,status,now,now,int(bool(read_only)),kind,last_step,
                 origin,context_hash,latency_budget_ms,
                 json.dumps(steps or [],ensure_ascii=False),int(bool(topology_ack))))
                self._conn.commit()
            except sqlite3.IntegrityError:
                self._conn.rollback()
                if origin=="grid_c_confirm" and context_hash:
                    r=self._conn.execute(
                        "SELECT job_id FROM jobs WHERE origin='grid_c_confirm' AND context_hash=?",
                        (context_hash,)).fetchone()
                    if r:
                        return self.get_job(r["job_id"])
                raise
        self.append_event(job_id,"job_created",{"goal":goal,"worker":worker,"kind":kind,"read_only":bool(read_only),
                                                "origin":origin,"context_hash":context_hash})
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

    def claim_next_queued(self, *, isolated: bool = False):
        """Production skips isolated_* origins. Isolated supervisors claim only that prefix."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            if isolated:
                where = "status='queued' AND IFNULL(origin,'') LIKE 'isolated_%' "
            else:
                where = "status='queued' AND IFNULL(origin,'') NOT LIKE 'isolated_%' "
            r=self._conn.execute(
                f"SELECT * FROM jobs WHERE {where}ORDER BY created_at LIMIT 1").fetchone()
            if not r:
                self._conn.commit()
                return None
            now=time.time()
            self._conn.execute("UPDATE jobs SET status='running',updated_at=? WHERE job_id=? AND status='queued'",
                               (now,r["job_id"]))
            self._conn.commit()
        job=self.get_job(r["job_id"])
        self.append_event(job["job_id"],"job_claimed",{"status":"running"})
        return job

    def next_queued(self):
        with self._lock:
            r=self._conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        return self._decode(r) if r else None

    def update_job(self, job_id, **fields):
        fields["updated_at"]=time.time()
        allowed={"worker","status","retry_count","last_step","last_artifact","pending_tool","cloud_allowed","updated_at","read_only","kind","receipt_event_id",
                 "origin","context_hash","latency_budget_ms","steps","topology_ack"}
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
            rows=self._conn.execute(
                "SELECT job_id,retry_count,worker,read_only,kind FROM jobs WHERE status='interrupted'"
            ).fetchall()
            n=0
            for r in rows:
                worker=r["worker"]
                read_only=bool(r["read_only"]) if "read_only" in r.keys() else True
                kind=r["kind"] if "kind" in r.keys() else "chat"
                if worker=="cc" or kind=="money_moving" or not read_only:
                    self._conn.execute(
                        "UPDATE jobs SET status='blocked',last_step=?,updated_at=? WHERE job_id=?",
                        ("RETRY_DENIED",time.time(),r["job_id"]))
                    continue
                if r["retry_count"] < max_retries:
                    self._conn.execute("""UPDATE jobs SET status='queued',
                    retry_count=retry_count+1,updated_at=? WHERE job_id=?""",(time.time(),r["job_id"]))
                    n+=1
                else:
                    self._conn.execute(
                        "UPDATE jobs SET status='failed',last_step=?,updated_at=? WHERE job_id=?",
                        ("RETRY_EXHAUSTED",time.time(),r["job_id"]))
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
        keys=r.keys()
        return {
          "job_id":r["job_id"],"channel":r["channel"],"goal":r["goal"],"worker":r["worker"],
          "allowed_tools":json.loads(r["allowed_tools"]),"allowed_paths":json.loads(r["allowed_paths"]),
          "cloud_allowed":bool(r["cloud_allowed"]),"approval_mode":r["approval_mode"],
          "status":r["status"],"retry_count":r["retry_count"],"last_step":r["last_step"],
          "last_artifact":r["last_artifact"],"pending_tool":r["pending_tool"],
          "created_at":r["created_at"],"updated_at":r["updated_at"],
          "read_only":bool(r["read_only"]) if "read_only" in keys else True,
          "kind":r["kind"] if "kind" in keys else "chat",
          "receipt_event_id":r["receipt_event_id"] if "receipt_event_id" in keys else None,
          "origin":r["origin"] if "origin" in keys else "",
          "context_hash":r["context_hash"] if "context_hash" in keys else "",
          "latency_budget_ms":r["latency_budget_ms"] if "latency_budget_ms" in keys else None,
          "steps":json.loads(r["steps"]) if "steps" in keys and r["steps"] else [],
          "topology_ack":bool(r["topology_ack"]) if "topology_ack" in keys else False,
        }

    def put_job_receipt(self, *, event_id: str, job_id: str, receipt_line: str, worker_output: str = ""):
        now=time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO job_receipts(event_id,job_id,receipt_line,worker_output,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(event_id) DO UPDATE SET
                     receipt_line=excluded.receipt_line,
                     worker_output=excluded.worker_output""",
                (event_id, job_id, receipt_line, worker_output or "", now))
            self._conn.commit()

    def get_job_receipt(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            r=self._conn.execute("SELECT * FROM job_receipts WHERE event_id=?",(event_id,)).fetchone()
        if not r:
            return None
        return {"event_id":r["event_id"],"job_id":r["job_id"],
                "receipt_line":r["receipt_line"],"worker_output":r["worker_output"],
                "created_at":r["created_at"]}

    def get_job_receipt_by_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            r=self._conn.execute(
                "SELECT * FROM job_receipts WHERE job_id=? ORDER BY created_at DESC LIMIT 1",
                (job_id,)).fetchone()
        if not r:
            return None
        return {"event_id":r["event_id"],"job_id":r["job_id"],
                "receipt_line":r["receipt_line"],"worker_output":r["worker_output"],
                "created_at":r["created_at"]}

    # ── missions ──────────────────────────────────────────────────────────
    _MISSION_FIELDS = {
        "goal","lane","worker","budget_hops","budget_tokens","budget_wall_s","budget_usd",
        "stop_conditions","status","created_by","lineage_root_event_id","hops_used","usd_used",
        "tokens_used","denied_streak","out_of_bounds","active_job_id","dossier_path",
        "close_reason","updated_at",
    }

    def create_mission(self, *, goal, lane, worker, budget_hops=0, budget_tokens=0,
                       budget_wall_s=0.0, budget_usd=0.0, stop_conditions=None, created_by=""):
        now=time.time()
        mid=f"M-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._conn.execute("""INSERT INTO missions(
              mission_id,goal,lane,worker,budget_hops,budget_tokens,budget_wall_s,budget_usd,
              stop_conditions,status,created_by,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (mid,goal,lane,worker,int(budget_hops),int(budget_tokens),float(budget_wall_s),float(budget_usd),
             json.dumps(stop_conditions or [],ensure_ascii=False),"proposed",created_by or "",now,now))
            self._conn.commit()
        return self.get_mission(mid)

    def get_mission(self, mission_id):
        with self._lock:
            r=self._conn.execute("SELECT * FROM missions WHERE mission_id=?",(mission_id,)).fetchone()
        if not r: raise KeyError(mission_id)
        return self._decode_mission(r)

    def list_missions(self, limit=100, status=None):
        sql="SELECT * FROM missions"
        args=[]
        if status:
            sql+=" WHERE status=?"; args.append(status)
        sql+=" ORDER BY updated_at DESC LIMIT ?"; args.append(limit)
        with self._lock:
            rows=self._conn.execute(sql,args).fetchall()
        return [self._decode_mission(r) for r in rows]

    def update_mission(self, mission_id, **fields):
        fields["updated_at"]=time.time()
        bad=set(fields)-self._MISSION_FIELDS
        if bad: raise ValueError(f"unsupported mission fields: {sorted(bad)}")
        pairs=", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE missions SET {pairs} WHERE mission_id=?",
                               list(fields.values())+[mission_id])
            self._conn.commit()
        return self.get_mission(mission_id)

    @staticmethod
    def _decode_mission(r):
        keys=r.keys()
        return {
            "mission_id":r["mission_id"],"goal":r["goal"],"lane":r["lane"],"worker":r["worker"],
            "budget_hops":r["budget_hops"],"budget_tokens":r["budget_tokens"],
            "budget_wall_s":r["budget_wall_s"],"budget_usd":r["budget_usd"],
            "stop_conditions":json.loads(r["stop_conditions"]) if "stop_conditions" in keys and r["stop_conditions"] else [],
            "status":r["status"],"created_by":r["created_by"] if "created_by" in keys else "",
            "lineage_root_event_id":r["lineage_root_event_id"] if "lineage_root_event_id" in keys else None,
            "hops_used":r["hops_used"] if "hops_used" in keys else 0,
            "usd_used":r["usd_used"] if "usd_used" in keys else 0.0,
            "tokens_used":r["tokens_used"] if "tokens_used" in keys else 0,
            "denied_streak":r["denied_streak"] if "denied_streak" in keys else 0,
            "out_of_bounds":r["out_of_bounds"] if "out_of_bounds" in keys else 0,
            "active_job_id":r["active_job_id"] if "active_job_id" in keys else None,
            "dossier_path":r["dossier_path"] if "dossier_path" in keys else None,
            "close_reason":r["close_reason"] if "close_reason" in keys else None,
            "created_at":r["created_at"],"updated_at":r["updated_at"],
        }
