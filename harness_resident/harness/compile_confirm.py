#!/usr/bin/env python3
"""Authenticated Grid C confirm. Binding hash is not authentication."""
from __future__ import annotations
import hashlib, json, sqlite3, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "state" / "compile_confirm.sqlite"
VERSION = "grid_c_confirm.v2"
DEFAULT_TTL_S = 30 * 60
DEFAULT_TOOLS = ["Read", "Grep", "Glob", "Write", "Edit", "Bash"]


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS candidates (
            candidate_id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            session_id TEXT NOT NULL,
            goal TEXT NOT NULL,
            worker TEXT NOT NULL,
            allowed_tools TEXT NOT NULL,
            allowed_paths TEXT NOT NULL,
            workdir TEXT NOT NULL,
            budget_ms INTEGER,
            expires_at REAL NOT NULL,
            version TEXT NOT NULL,
            binding_hash TEXT NOT NULL,
            job_id TEXT,
            created_at REAL NOT NULL
        )"""
    )
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS cand_owner_id ON candidates(owner, candidate_id)"
    )
    return con


def _canon(rec: dict) -> str:
    keys = (
        "candidate_id", "owner", "session_id", "goal", "worker",
        "allowed_tools", "allowed_paths", "workdir", "budget_ms",
        "expires_at", "version",
    )
    payload = {k: rec[k] for k in keys}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def binding_hash(rec: dict) -> str:
    return hashlib.sha3_256(_canon(rec).encode()).hexdigest()


def register(*, owner: str, session_id: str, goal: str, budget_ms: int | None = None) -> dict:
    owner = str(owner or "").strip()
    goal = str(goal or "").strip()
    session_id = str(session_id or "").strip() or "default"
    if not owner or not goal:
        return {"ok": False, "error": "owner and goal required", "http": 400}
    now = time.time()
    rec = {
        "candidate_id": "C-" + uuid.uuid4().hex[:16],
        "owner": owner,
        "session_id": session_id,
        "goal": goal,
        "worker": "cc",
        "allowed_tools": list(DEFAULT_TOOLS),
        "allowed_paths": [],
        "workdir": "/work",
        "budget_ms": int(budget_ms or 1_800_000),
        "expires_at": now + DEFAULT_TTL_S,
        "version": VERSION,
    }
    rec["binding_hash"] = binding_hash(rec)
    con = _conn()
    try:
        con.execute(
            """INSERT INTO candidates(
                candidate_id,owner,session_id,goal,worker,allowed_tools,allowed_paths,
                workdir,budget_ms,expires_at,version,binding_hash,job_id,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)""",
            (
                rec["candidate_id"], rec["owner"], rec["session_id"], rec["goal"],
                rec["worker"], json.dumps(rec["allowed_tools"]), json.dumps(rec["allowed_paths"]),
                rec["workdir"], rec["budget_ms"], rec["expires_at"], rec["version"],
                rec["binding_hash"], now,
            ),
        )
        con.commit()
    finally:
        con.close()
    return {"ok": True, **{k: rec[k] for k in (
        "candidate_id", "binding_hash", "expires_at", "version", "worker", "session_id"
    )}}


def lookup(candidate_id: str, *, owner: str) -> dict | None:
    con = _conn()
    try:
        row = con.execute(
            "SELECT * FROM candidates WHERE candidate_id=? AND owner=?",
            (candidate_id, owner),
        ).fetchone()
    finally:
        con.close()
    if not row:
        return None
    return dict(row)


def _approval_mode() -> str:
    # Authenticated confirm is the approval. Policy may force wait.
    import os
    raw = (os.getenv("GRID_CC_CONFIRM_APPROVAL") or "").strip()
    if raw in {"auto", "write_ok_no_deploy"}:
        return raw
    return "auto"


def submit(body: dict, *, create_job, owner: str) -> dict:
    extra = set(body) - {"candidate_id", "binding_hash", "session_id"}
    if extra & {"approval_mode", "worker", "token", "Authorization", "origin", "lane",
                "allowed_paths", "allowed_tools", "budget_ms", "workdir", "goal"}:
        return {"ok": False, "error": "client cannot set worker/approval/scope", "http": 400}
    cid = str(body.get("candidate_id") or "").strip()
    got = str(body.get("binding_hash") or "").strip()
    owner = str(owner or "").strip()
    if not cid or not got or not owner:
        return {"ok": False, "error": "candidate required", "http": 400}
    con = _conn()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM candidates WHERE candidate_id=? AND owner=?",
            (cid, owner),
        ).fetchone()
        if not row:
            con.rollback()
            return {"ok": False, "error": "unknown_or_foreign_candidate", "http": 403}
        rec = dict(row)
        if rec["binding_hash"] != got:
            con.rollback()
            return {"ok": False, "error": "modified_candidate", "http": 409}
        jid_now = str(rec.get("job_id") or "")
        if jid_now and not jid_now.startswith("reserved:"):
            con.commit()
            return {"ok": True, "idempotent": True, "candidate_id": cid,
                    "job_id": jid_now, "binding_hash": rec["binding_hash"],
                    "origin": "grid_c_confirm"}
        expect = binding_hash({
            "candidate_id": rec["candidate_id"],
            "owner": rec["owner"],
            "session_id": rec["session_id"],
            "goal": rec["goal"],
            "worker": rec["worker"],
            "allowed_tools": json.loads(rec["allowed_tools"]),
            "allowed_paths": json.loads(rec["allowed_paths"]),
            "workdir": rec["workdir"],
            "budget_ms": rec["budget_ms"],
            "expires_at": rec["expires_at"],
            "version": rec["version"],
        })
        if expect != rec["binding_hash"]:
            con.rollback()
            return {"ok": False, "error": "binding_mismatch", "http": 409}
        if time.time() > float(rec["expires_at"]) and not jid_now.startswith("reserved:"):
            con.rollback()
            return {"ok": False, "error": "expired_candidate", "http": 409}
        if not jid_now.startswith("reserved:"):
            reserved = "reserved:" + cid
            cur = con.execute(
                "UPDATE candidates SET job_id=? WHERE candidate_id=? AND owner=? AND job_id IS NULL",
                (reserved, cid, owner),
            )
            if cur.rowcount != 1:
                row2 = con.execute(
                    "SELECT job_id FROM candidates WHERE candidate_id=? AND owner=?",
                    (cid, owner),
                ).fetchone()
                existing = str(row2["job_id"] if row2 else "")
                if existing and not existing.startswith("reserved:"):
                    con.commit()
                    return {"ok": True, "idempotent": True, "candidate_id": cid,
                            "job_id": existing, "binding_hash": rec["binding_hash"],
                            "origin": "grid_c_confirm"}
            con.commit()
        else:
            con.commit()
    finally:
        con.close()
    reserved = "reserved:" + cid
    try:
        job = create_job(
            channel="grid",
            goal=rec["goal"],
            worker="cc",
            allowed_tools=json.loads(rec["allowed_tools"]),
            allowed_paths=json.loads(rec["allowed_paths"]),
            cloud_allowed=False,
            approval_mode=_approval_mode(),
            read_only=False,
            kind="chat",
            origin="grid_c_confirm",
            context_hash=rec["binding_hash"],
            latency_budget_ms=rec["budget_ms"],
        )
    except Exception:
        conb = _conn()
        try:
            conb.execute(
                "UPDATE candidates SET job_id=NULL WHERE candidate_id=? AND owner=? AND job_id=?",
                (cid, owner, reserved),
            )
            conb.commit()
        finally:
            conb.close()
        raise
    jid = job.get("job_id")
    con2 = _conn()
    try:
        con2.execute("BEGIN IMMEDIATE")
        cur = con2.execute(
            "UPDATE candidates SET job_id=? WHERE candidate_id=? AND owner=? AND job_id=?",
            (jid, cid, owner, reserved),
        )
        if cur.rowcount != 1:
            row2 = con2.execute(
                "SELECT job_id FROM candidates WHERE candidate_id=? AND owner=?",
                (cid, owner),
            ).fetchone()
            con2.commit()
            existing = (row2["job_id"] if row2 else jid)
            return {"ok": True, "idempotent": True, "candidate_id": cid,
                    "job_id": existing, "binding_hash": rec["binding_hash"],
                    "origin": "grid_c_confirm"}
        con2.commit()
        return {
            "ok": True, "idempotent": False, "candidate_id": cid,
            "job_id": jid, "binding_hash": rec["binding_hash"],
            "worker": "cc", "origin": "grid_c_confirm",
            "status": job.get("status"),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    finally:
        con2.close()
