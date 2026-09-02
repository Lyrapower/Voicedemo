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
