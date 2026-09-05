"""日记存储 — 长在 FIELD 里,不是 md 文件。sqlite,本地私有。
   宪法:private local artifact / no training / no scoring / no auto-read / Lyra-only.
   append-only + sha256 链(防无声改写)。"""
from __future__ import annotations
import os, json, sqlite3, hashlib, datetime as dt
from .diary_guard import reject_probe_text

DB = os.environ.get("DIARY_DB",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "diary.db"))

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS entries(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL, text TEXT NOT NULL,
        prev_hash TEXT, hash TEXT NOT NULL)""")
    try: os.chmod(DB, 0o600)
    except OSError: pass
    return c

def add(text: str) -> dict:
    """写一篇。空文本也存('今天选择不写'),append-only。"""
    text = (text or "").strip() or "(今天选择不写)"
    reject_probe_text(text, what="diary entry")
    c = _conn()
    prev = c.execute("SELECT hash FROM entries ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = prev[0] if prev else ""
    ts = dt.datetime.now().isoformat(timespec="seconds")
    h = hashlib.sha256((prev_hash + ts + text).encode()).hexdigest()
    c.execute("INSERT INTO entries(ts,text,prev_hash,hash) VALUES(?,?,?,?)",
              (ts, text, prev_hash, h))
    c.commit()
    row_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.close()
    return {"id": row_id, "ts": ts, "hash": h[:12]}

def all_entries() -> list[dict]:
    c = _conn()
    rows = c.execute("SELECT id,ts,text FROM entries ORDER BY id").fetchall()
    c.close()
    return [{"id": r[0], "ts": r[1], "text": r[2]} for r in rows]

def verify() -> dict:
    """校验 hash 链,防无声改写。"""
    c = _conn()
    rows = c.execute("SELECT ts,text,prev_hash,hash FROM entries ORDER BY id").fetchall()
    c.close()
    prev = ""
    for i, (ts, text, ph, h) in enumerate(rows, 1):
        expect = hashlib.sha256((prev + ts + text).encode()).hexdigest()
        if ph != prev or h != expect:
            return {"ok": False, "broken_at": i}
        prev = h
    return {"ok": True, "count": len(rows)}
