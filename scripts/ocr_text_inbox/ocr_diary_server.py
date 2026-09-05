#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拾字簿 · OCR Diary — phone-facing reader/editor for OCR_Text_Inbox, served over Tailscale.

Run on the Mac (Terminal.app is fine; no Photos permission needed — this only reads md files):

    python3 ocr_diary.py

Then on the phone (same tailnet):  http://<mac-tailscale-name>:8791

Environment overrides:
    OCR_INBOX=~/Desktop/OCR_Text_Inbox     inbox root
    OCR_DIARY_PORT=8791                    listen port
    OCR_DIARY_TOKEN=<secret>               if set, requests need ?token=<secret>
                                           (bookmark http://mac:8791/?token=... on the phone)

What it does:
  * Timeline reader (month → day → note), diary/book styling, Chinese-first.
  * Edit a note's body in place (frontmatter preserved; adds `edited:` timestamp).
  * 朱批 mark: toggles a `marked` tag in the note's frontmatter.
  * Delete: moves the md into _trash/<month>/ AND records the asset in
    deleted_assets.json — see the weekly_sync patch below, otherwise a deleted
    note will be re-imported on the next sync (Photos asset still exists).
  * Rebuild index: regenerates ocr_index.json for ALL months (merge-safe; fixes
    the partial-rebuild-overwrites-everything footgun in build_monthly_auto.py).
  * SQLite snapshot: GET /snapshot.db downloads the whole library as one .db
    (notes table + FTS5 trigram full-text search when available) for offline use.

Suggested weekly_sync.py patch (skip resurrecting deleted notes):

    # near the "uuid.md exists -> skip" check:
    tomb = json.loads((INBOX / "deleted_assets.json").read_text()) \
           if (INBOX / "deleted_assets.json").exists() else {"deleted": []}
    dead = {d["uuid"] for d in tomb["deleted"]}
    if uuid_part in dead:
        continue

Stdlib only. No packages to install.
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

INBOX = Path(os.environ.get("OCR_INBOX", "~/Desktop/OCR_Text_Inbox")).expanduser()
PORT = int(os.environ.get("OCR_DIARY_PORT", "8791"))
TOKEN = os.environ.get("OCR_DIARY_TOKEN", "")

TRASH = INBOX / "_trash"
TOMBSTONES = INBOX / "deleted_assets.json"

# Memory Palace vault (归房 target). Set PALACE_VAULT to override discovery.
PALACE_ENV = os.environ.get("PALACE_VAULT", "")
PALACE_CANDIDATES = [
    "~/memory-palace/vault",
    "~/Projects/memory-palace/vault",
    "~/Projects/demo/memory-palace/vault",
    "~/Desktop/memory-palace/vault",
]
ROOM_RE = re.compile(r"^\d{2}-")


def palace_vault():
    if PALACE_ENV:
        p = Path(PALACE_ENV).expanduser()
        return p if p.is_dir() else None
    for c in PALACE_CANDIDATES:
        p = Path(c).expanduser()
        if p.is_dir():
            return p
    return None

MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
UUID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.S)


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- note parsing

def parse_note(path: Path):
    """Return (fm_raw, fm_dict, tags, body). Body = text after frontmatter and
    the '# OCR Note' heading, stripped."""
    text = path.read_text(encoding="utf-8", errors="replace")
    m = FM_RE.match(text)
    fm_raw = m.group(1) if m else ""
    rest = text[m.end():] if m else text
    body = re.sub(r"^\s*#\s*OCR Note\s*\r?\n", "", rest, count=1).strip()

    fm, tags, in_tags = {}, [], False
    for line in fm_raw.splitlines():
        stripped = line.strip()
        if stripped == "tags:" or stripped.startswith("tags:"):
            in_tags = True
            continue
        if in_tags and stripped.startswith("- "):
            tags.append(stripped[2:].strip())
            continue
        in_tags = False
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm_raw, fm, tags, body


def write_note(path: Path, fm_raw: str, body: str):
    path.write_text("---\n%s\n---\n\n# OCR Note\n\n%s\n" % (fm_raw, body.strip()),
                    encoding="utf-8")


def set_edited(fm_raw: str) -> str:
    now = utcnow()
    if re.search(r"^edited:", fm_raw, re.M):
        return re.sub(r"^edited:.*$", "edited: " + now, fm_raw, flags=re.M)
    return fm_raw + "\nedited: " + now


def toggle_marked(fm_raw: str, tags: list):
    if "marked" in tags:
        lines = [l for l in fm_raw.splitlines() if l.strip() != "- marked"]
        return "\n".join(lines), False
    if re.search(r"^tags:\s*$", fm_raw, re.M):
        fm_raw = re.sub(r"^tags:\s*$", "tags:\n  - marked", fm_raw, count=1, flags=re.M)
    else:
        fm_raw = fm_raw + "\ntags:\n  - marked"
    return fm_raw, True


def created_of(path: Path, fm: dict) -> str:
    c = fm.get("created", "")
    if c:
        return c
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)\
        .strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- library scan

def month_dirs():
    if not INBOX.exists():
        return []
    return sorted((d for d in INBOX.iterdir()
                   if d.is_dir() and MONTH_RE.match(d.name)), key=lambda d: d.name)


def scan_month(ym: str, with_body=True):
    folder = INBOX / ym
    notes = []
    if not folder.is_dir():
        return notes
    for p in sorted(folder.glob("*.md")):
        if p.name.startswith("_"):
            continue
        fm_raw, fm, tags, body = parse_note(p)
        n = {
            "uuid": p.stem,
            "month": ym,
            "created": created_of(p, fm),
            "edited": fm.get("edited", ""),
            "marked": "marked" in tags,
            "tags": tags,
            "chars": len(body),
            "preview": " ".join(body.split())[:120],
        }
        if with_body:
            n["body"] = body
        notes.append(n)
    notes.sort(key=lambda n: (n["created"], n["uuid"]))
    return notes


def note_path(ym: str, uuid: str) -> Path:
    if not MONTH_RE.match(ym) or not UUID_RE.match(uuid) or ".." in uuid:
        raise ValueError("bad path")
    p = (INBOX / ym / (uuid + ".md")).resolve()
    if INBOX.resolve() not in p.parents and p.parent.parent != INBOX.resolve():
        raise ValueError("bad path")
    return p


# ---------------------------------------------------------------- operations

def op_save(ym, uuid, body):
    p = note_path(ym, uuid)
    fm_raw, fm, tags, _ = parse_note(p)
    write_note(p, set_edited(fm_raw), body)
    return {"ok": True, "edited": utcnow()}


def op_mark(ym, uuid):
    p = note_path(ym, uuid)
    fm_raw, fm, tags, body = parse_note(p)
    fm_raw, marked = toggle_marked(fm_raw, tags)
    write_note(p, fm_raw, body)
    return {"ok": True, "marked": marked}


def op_delete(ym, uuid):
    p = note_path(ym, uuid)
    fm_raw, fm, tags, body = parse_note(p)
    dest_dir = TRASH / ym
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(dest_dir / p.name))

    data = {"deleted": []}
    if TOMBSTONES.exists():
        try:
            data = json.loads(TOMBSTONES.read_text(encoding="utf-8"))
        except Exception:
            pass
    data.setdefault("deleted", []).append({
        "uuid": uuid, "month": ym,
        "asset_id": fm.get("asset_id", ""), "at": utcnow(),
    })
    TOMBSTONES.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return {"ok": True, "trashed_to": str(dest_dir / p.name)}


def _slug(s, maxlen=40):
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r'[\\/:"*?<>|#\[\]]+', "", s)
    return s[:maxlen] or "untitled"


def op_rooms():
    v = palace_vault()
    if not v:
        return {"vault": None, "rooms": []}
    rooms = sorted(d.name for d in v.iterdir()
                   if d.is_dir() and ROOM_RE.match(d.name)
                   and not d.name.startswith("99"))  # 99-向量索引 = machine layer
    return {"vault": str(v), "rooms": rooms}


def _update_room_index(room_dir: Path):
    """Rewrite the AUTO-INDEX block in the room's _index.md (palace_lib style)."""
    idx = room_dir / "_index.md"
    entries = []
    for f in sorted(room_dir.glob("*.md")):
        if f.name == "_index.md":
            continue
        _, ffm, _, _ = parse_note(f)
        entries.append("- [[%s]] · %s" % (f.stem, ffm.get("status", "?")))
    block = "<!-- AUTO-INDEX-START -->\n" + "\n".join(entries) + "\n<!-- AUTO-INDEX-END -->"
    if idx.exists():
        txt = idx.read_text(encoding="utf-8")
        if "<!-- AUTO-INDEX-START -->" in txt and "<!-- AUTO-INDEX-END -->" in txt:
            txt = re.sub(r"<!-- AUTO-INDEX-START -->.*?<!-- AUTO-INDEX-END -->",
                         lambda m: block, txt, flags=re.S)
        else:
            txt += "\n" + block + "\n"
    else:
        txt = ("---\ntype: room-index\nroom: %s\ncreated: %s\n---\n# %s\n\n%s\n"
               % (room_dir.name, datetime.now().strftime("%Y-%m-%d"),
                  room_dir.name, block))
    idx.write_text(txt, encoding="utf-8")


def op_file_to_room(ym, uuid, room):
    """归房: copy an OCR note into a Palace room using the inbox-note schema.
    Copy, not move — the OCR inbox stays the complete raw archive; the vault
    holds the curated layer, with original_file pointing back."""
    v = palace_vault()
    if not v:
        raise ValueError("palace vault not found — set PALACE_VAULT")
    if room not in op_rooms()["rooms"]:
        raise ValueError("bad room")
    p = note_path(ym, uuid)
    fm_raw, fm, tags, body = parse_note(p)

    first = next((l for l in body.splitlines() if l.strip()), uuid)
    title = first.strip().lstrip("#").strip()[:30] or uuid
    dest = v / room / (_slug(title) + ".md")
    if dest.exists():
        dest = v / room / (_slug(title) + "-"
                           + datetime.now().strftime("%H%M%S") + ".md")

    keep = [t for t in tags
            if t not in ("ocr", "screenshot", "weekly_sync", "marked", "filed")]
    fm_out = ("type: inbox-note\n"
              "created: %s\n"
              "source: ocr\n"
              "status: sorted\n"
              "room: %s\n"
              "tags: [%s]\n"
              "original_file: %s\n"
              % (datetime.now().strftime("%Y-%m-%d"), room,
                 ", ".join(keep), p))
    dest.write_text("---\n%s---\n\n# %s\n\n%s\n\n> 拾字簿归档 · 截图 %s\n"
                    % (fm_out, title, body, fm.get("created", "?")),
                    encoding="utf-8")
    _update_room_index(v / room)

    if "filed" not in tags:  # flag the source note so the diary shows 已归
        if re.search(r"^tags:", fm_raw, re.M):
            fm_raw = re.sub(r"^tags:", "tags:\n  - filed", fm_raw,
                            count=1, flags=re.M)
        else:
            fm_raw += "\ntags:\n  - filed"
        write_note(p, fm_raw, body)
    return {"ok": True, "filed_to": str(dest)}


def op_rebuild_index():
    """Full, merge-safe rebuild of ocr_index.json in the documented schema."""
    months = []
    for d in month_dirs():
        files = []
        for p in sorted(d.glob("*.md")):
            if p.name.startswith("_"):
                continue
            fm_raw, fm, tags, body = parse_note(p)
            if not body or body.lower() == "no text recognized":
                continue
            files.append({
                "file": "%s/%s" % (d.name, p.name),
                "created": created_of(p, fm),
                "text_preview": " ".join(body.split())[:120],
                "text_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            })
        files.sort(key=lambda f: (f["created"], f["file"]))
        months.append({
            "month": d.name,
            "monthly_review": "%s/_monthly_review.md" % d.name,
            "file_count": len(files),
            "files": files,
        })
    idx = {
        "created_at": utcnow(),
        "source_folder": str(INBOX),
        "ocr_engine": "macos_vision_zh_en",
        "months": months,
    }
    (INBOX / "ocr_index.json").write_text(
        json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "months": len(months),
            "notes": sum(m["file_count"] for m in months)}


def op_snapshot() -> bytes:
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        con = sqlite3.connect(tmp)
        con.execute("""CREATE TABLE notes(
            uuid TEXT PRIMARY KEY, month TEXT, created TEXT, edited TEXT,
            marked INTEGER, tags TEXT, chars INTEGER, body TEXT, text_hash TEXT)""")
        fts = True
        try:
            con.execute("CREATE VIRTUAL TABLE notes_fts USING fts5("
                        "body, uuid UNINDEXED, tokenize='trigram')")
        except sqlite3.OperationalError:
            fts = False
        for d in month_dirs():
            for n in scan_month(d.name, with_body=True):
                h = hashlib.sha256(n["body"].encode("utf-8")).hexdigest()
                con.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?,?,?,?,?,?,?)",
                            (n["uuid"], n["month"], n["created"], n["edited"],
                             1 if n["marked"] else 0, json.dumps(n["tags"]),
                             n["chars"], n["body"], h))
                if fts:
                    con.execute("INSERT INTO notes_fts(body, uuid) VALUES(?,?)",
                                (n["body"], n["uuid"]))
        con.execute("CREATE TABLE meta(k TEXT, v TEXT)")
        con.execute("INSERT INTO meta VALUES('created_at', ?)", (utcnow(),))
        con.execute("INSERT INTO meta VALUES('fts', ?)", ("trigram" if fts else "none",))
        con.commit()
        con.close()
        return Path(tmp).read_bytes()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------- HTTP layer

class Handler(BaseHTTPRequestHandler):
    server_version = "OCRDiary/1.0"

    # -- helpers
    def _authed(self, query):
        if not TOKEN:
            return True
        return (query.get("token", [""])[0] == TOKEN
                or self.headers.get("X-Token", "") == TOKEN)

    def _send(self, code, body, ctype="application/json; charset=utf-8",
              extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        n = int(self.headers.get("Content-Length", "0") or "0")
        if n <= 0:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def log_message(self, fmt, *args):  # quieter log
        print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

    # -- routing
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        parts = [p for p in u.path.split("/") if p]
        if not self._authed(q):
            return self._send(401, {"error": "token required"})
        try:
            if u.path == "/" or u.path == "/index.html":
                return self._send(200, PAGE, "text/html; charset=utf-8")
            if parts == ["api", "rooms"]:
                return self._send(200, op_rooms())
            if parts == ["api", "months"]:
                out = [{"month": d.name,
                        "count": sum(1 for p in d.glob("*.md")
                                     if not p.name.startswith("_"))}
                       for d in month_dirs()]
                return self._send(200, out)
            if len(parts) == 3 and parts[:2] == ["api", "month"]:
                ym = parts[2]
                if not MONTH_RE.match(ym):
                    return self._send(400, {"error": "bad month"})
                return self._send(200, {"month": ym, "notes": scan_month(ym)})
            if parts == ["snapshot.db"]:
                blob = op_snapshot()
                name = "ocr_snapshot_%s.db" % datetime.now().strftime("%Y%m%d_%H%M")
                return self._send(200, blob, "application/octet-stream",
                                  {"Content-Disposition":
                                   'attachment; filename="%s"' % name})
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        parts = [p for p in u.path.split("/") if p]
        if not self._authed(q):
            return self._send(401, {"error": "token required"})
        try:
            if parts == ["api", "rebuild"]:
                return self._send(200, op_rebuild_index())
            if len(parts) == 4 and parts[0] == "api":
                op, ym, uuid = parts[1], parts[2], parts[3]
                if op == "save":
                    body = self._json_body().get("body", "")
                    return self._send(200, op_save(ym, uuid, body))
                if op == "mark":
                    return self._send(200, op_mark(ym, uuid))
                if op == "delete":
                    return self._send(200, op_delete(ym, uuid))
                if op == "room":
                    room = self._json_body().get("room", "")
                    return self._send(200, op_file_to_room(ym, uuid, room))
            return self._send(404, {"error": "not found"})
        except FileNotFoundError:
            return self._send(404, {"error": "note not found"})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})


# ---------------------------------------------------------------- frontend

PAGE = r"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>拾字簿</title>
<style>
:root{
  --paper:#EFE9DC; --card:#F7F2E7; --ink:#2A241D; --faint:#8B8172;
  --rule:#DAD1BE; --zhu:#A2301F; --zhu-soft:#A2301F22;
}
@media (prefers-color-scheme: dark){
  :root{ --paper:#171310; --card:#1F1A15; --ink:#E8E0D0; --faint:#9A8F7E;
         --rule:#3A332A; --zhu:#C8503C; --zhu-soft:#C8503C2E; }
}
*{box-sizing:border-box; -webkit-tap-highlight-color:transparent}
html,body{margin:0; background:var(--paper); color:var(--ink);
  font-family:"Songti SC","Noto Serif SC","Source Han Serif SC",Georgia,serif;
  font-size:16px; line-height:1.75}
.mono{font-family:ui-monospace,"SF Mono",Menlo,monospace; font-size:.78rem;
  letter-spacing:.03em; color:var(--faint)}

header{position:sticky; top:0; z-index:5; background:var(--paper);
  border-bottom:1px solid var(--rule); padding:.6rem 1rem .5rem;
  padding-top:calc(.6rem + env(safe-area-inset-top))}
.masthead{display:flex; align-items:baseline; justify-content:space-between}
.masthead h1{margin:0; font-size:1.25rem; font-weight:600; letter-spacing:.35em}
.tools{display:flex; gap:.5rem}
.tools button{background:none; border:1px solid var(--rule); color:var(--ink);
  font:inherit; font-size:.8rem; border-radius:2px; padding:.15rem .55rem}
.tools button.zhu-on{border-color:var(--zhu); color:var(--zhu)}

.spine{display:flex; gap:.45rem; overflow-x:auto; padding:.55rem 0 .15rem;
  scrollbar-width:none}
.spine::-webkit-scrollbar{display:none}
.spine button{flex:0 0 auto; border:1px solid var(--rule); background:var(--card);
  color:var(--ink); font:inherit; font-size:.82rem; padding:.2rem .6rem;
  border-radius:2px}
.spine button.on{border-color:var(--ink); box-shadow:inset 0 0 0 1px var(--ink)}
.spine .cnt{color:var(--faint); font-size:.7rem; margin-left:.3em}

.search{margin-top:.45rem}
.search input{width:100%; border:1px solid var(--rule); background:var(--card);
  color:var(--ink); font:inherit; font-size:.9rem; padding:.35rem .6rem;
  border-radius:2px; outline:none}
.search input:focus{border-color:var(--faint)}

main{max-width:44rem; margin:0 auto; padding:0 1rem 5rem}
.dayhead{display:flex; align-items:center; gap:.7rem; margin:1.6rem 0 .4rem}
.dayhead .d{font-size:.95rem; font-weight:600; white-space:nowrap}
.dayhead .w{color:var(--faint); font-size:.8rem; white-space:nowrap}
.dayhead::after{content:""; flex:1; border-top:1px solid var(--rule)}

.entry{position:relative; background:var(--card); border:1px solid var(--rule);
  border-radius:2px; padding:.7rem .85rem .6rem; margin:.55rem 0}
.entry.marked{border-left:3px solid var(--zhu)}
.entry .meta{display:flex; align-items:center; gap:.6rem; margin-bottom:.25rem}
.entry .seal{margin-left:auto; width:1.25rem; height:1.25rem; border:1.5px solid var(--zhu);
  color:var(--zhu); border-radius:2px; display:none; align-items:center;
  justify-content:center; font-size:.72rem; font-weight:700;
  transform:rotate(-4deg); background:var(--zhu-soft)}
.entry.marked .seal{display:flex}
.entry .txt{white-space:pre-wrap; word-break:break-word; font-size:.94rem}
.entry .txt.clamp{display:-webkit-box; -webkit-line-clamp:3;
  -webkit-box-orient:vertical; overflow:hidden}
.entry .more{color:var(--faint); font-size:.78rem; margin-top:.25rem}
.entry .acts{display:none; gap:.6rem; margin-top:.6rem; border-top:1px dashed var(--rule);
  padding-top:.5rem}
.entry.open .acts{display:flex}
.acts button{background:none; border:1px solid var(--rule); color:var(--ink);
  font:inherit; font-size:.8rem; padding:.15rem .6rem; border-radius:2px}
.acts button.danger{color:var(--zhu); border-color:var(--zhu)}
.entry textarea{width:100%; min-height:9rem; font:inherit; font-size:.94rem;
  line-height:1.7; background:var(--paper); color:var(--ink);
  border:1px solid var(--rule); border-radius:2px; padding:.5rem; outline:none}
.editedflag{color:var(--faint); font-size:.72rem}

.empty{color:var(--faint); text-align:center; margin:4rem 0; letter-spacing:.2em}
@media (prefers-reduced-motion: no-preference){
  .entry{animation:rise .25s ease both}
  @keyframes rise{from{opacity:0; transform:translateY(4px)} to{opacity:1}}
}
</style>
</head>
<body>
<header>
  <div class="masthead">
    <h1>拾字簿</h1>
    <div class="tools">
      <button id="filterZhu" title="只看朱批">批</button>
      <button id="btnSnap" title="下载 SQLite 快照">快照</button>
      <button id="btnRebuild" title="重建 ocr_index.json">索引</button>
    </div>
  </div>
  <div class="spine" id="spine"></div>
  <div class="search"><input id="q" type="search" placeholder="检索本册文字…"></div>
</header>
<main id="main"><div class="empty">载 入 中</div></main>

<script>
const TOKEN = new URLSearchParams(location.search).get('token') || '';
const api = (p, opt) => fetch(p + (TOKEN ? (p.includes('?')?'&':'?') + 'token=' + encodeURIComponent(TOKEN) : ''), opt)
  .then(r => { if(!r.ok) return r.json().then(j=>{throw new Error(j.error||r.status)}); return r; });

const WEEK = ['日','一','二','三','四','五','六'];
let months = [], curMonth = '', notes = [], onlyZhu = false, query = '';

function localDate(iso){ const d = new Date(iso); return isNaN(d) ? null : d; }
function dkey(d){ return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0'); }
function hhmm(d){ return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0'); }

async function loadMonths(){
  months = await (await api('/api/months')).json();
  const spine = document.getElementById('spine');
  spine.innerHTML = '';
  months.slice().reverse().forEach(m => {
    const b = document.createElement('button');
    b.innerHTML = m.month + '<span class="cnt mono">' + m.count + '</span>';
    b.onclick = () => selectMonth(m.month);
    b.dataset.m = m.month;
    spine.appendChild(b);
  });
  if(months.length) selectMonth(months[months.length-1].month);
  else document.getElementById('main').innerHTML = '<div class="empty">册 中 无 字</div>';
}

async function selectMonth(ym){
  curMonth = ym;
  document.querySelectorAll('.spine button').forEach(b => b.classList.toggle('on', b.dataset.m===ym));
  document.getElementById('main').innerHTML = '<div class="empty">载 入 中</div>';
  const data = await (await api('/api/month/' + ym)).json();
  notes = data.notes;
  render();
}

function render(){
  const main = document.getElementById('main');
  main.innerHTML = '';
  const q = query.trim();
  let shown = notes.filter(n => (!onlyZhu || n.marked) && (!q || (n.body||'').includes(q)));
  if(!shown.length){ main.innerHTML = '<div class="empty">此 册 无 相 应 字 迹</div>'; return; }
  // newest day first, entries within a day in time order
  const byDay = new Map();
  shown.forEach(n => {
    const d = localDate(n.created) || new Date(0);
    const k = dkey(d);
    if(!byDay.has(k)) byDay.set(k, {date:d, items:[]});
    byDay.get(k).items.push(n);
  });
  [...byDay.values()].sort((a,b)=>b.date-a.date).forEach(g => {
    const h = document.createElement('div');
    h.className = 'dayhead';
    h.innerHTML = '<span class="d">'+dkey(g.date)+'</span><span class="w">週'+WEEK[g.date.getDay()]+' · '+g.items.length+' 条</span>';
    main.appendChild(h);
    g.items.forEach(n => main.appendChild(entryEl(n)));
  });
}

function entryEl(n){
  const el = document.createElement('article');
  el.className = 'entry' + (n.marked ? ' marked' : '');
  const d = localDate(n.created);
  el.innerHTML =
    '<div class="meta"><span class="mono">'+(d?hhmm(d):'——')+'</span>'
    + (n.edited ? '<span class="editedflag">已改</span>' : '')
    + (n.tags && n.tags.includes('filed') ? '<span class="editedflag">已归</span>' : '')
    + '<span class="mono" style="opacity:.6">'+n.chars+' 字</span>'
    + '<span class="seal">批</span></div>'
    + '<div class="txt clamp"></div><div class="more">展开 ▾</div>'
    + '<div class="acts">'
    +   '<button class="a-edit">修改</button>'
    +   '<button class="a-mark">'+(n.marked?'去批':'朱批')+'</button>'
    +   '<button class="a-room">归房</button>'
    +   '<button class="a-del danger">弃置</button>'
    + '</div>';
  el.querySelector('.txt').textContent = n.body || n.preview || '';
  const txt = el.querySelector('.txt'), more = el.querySelector('.more');
  function toggleOpen(){
    el.classList.toggle('open');
    const open = el.classList.contains('open');
    txt.classList.toggle('clamp', !open);
    more.textContent = open ? '收起 ▴' : '展开 ▾';
  }
  txt.onclick = toggleOpen; more.onclick = toggleOpen;

  el.querySelector('.a-mark').onclick = async () => {
    const r = await (await api('/api/mark/'+n.month+'/'+n.uuid, {method:'POST'})).json();
    n.marked = r.marked; render();
  };
  el.querySelector('.a-room').onclick = async () => {
    if(!window._rooms) window._rooms = await (await api('/api/rooms')).json();
    const R = window._rooms;
    if(!R.vault){ alert('未找到记忆宫殿 vault。启动时设 PALACE_VAULT=路径'); return; }
    const acts = el.querySelector('.acts');
    acts.innerHTML = R.rooms.map(r =>
      '<button class="a-r" data-r="'+r+'">'+r+'</button>').join('')
      + '<button class="a-cancel">作罢</button>';
    acts.style.flexWrap = 'wrap';
    acts.querySelectorAll('.a-r').forEach(b => b.onclick = async () => {
      await api('/api/room/'+n.month+'/'+n.uuid,
        {method:'POST', headers:{'Content-Type':'application/json'},
         body:JSON.stringify({room:b.dataset.r})});
      if(!n.tags.includes('filed')) n.tags.push('filed');
      render();
    });
    acts.querySelector('.a-cancel').onclick = () => render();
  };
  el.querySelector('.a-del').onclick = async () => {
    if(!confirm('弃置这一条？（移入 _trash，可手动找回）')) return;
    await api('/api/delete/'+n.month+'/'+n.uuid, {method:'POST'});
    notes = notes.filter(x => x.uuid !== n.uuid); render();
  };
  el.querySelector('.a-edit').onclick = () => {
    if(el.querySelector('textarea')) return;
    const ta = document.createElement('textarea'); ta.value = n.body || '';
    txt.style.display='none'; more.style.display='none';
    el.insertBefore(ta, el.querySelector('.acts'));
    const acts = el.querySelector('.acts');
    acts.innerHTML = '<button class="a-save">存好</button><button class="a-cancel">作罢</button>';
    acts.querySelector('.a-save').onclick = async () => {
      const r = await (await api('/api/save/'+n.month+'/'+n.uuid,
        {method:'POST', headers:{'Content-Type':'application/json'},
         body:JSON.stringify({body:ta.value})})).json();
      n.body = ta.value; n.chars = ta.value.length; n.edited = r.edited;
      n.preview = ta.value.split(/\s+/).join(' ').slice(0,120);
      render();
    };
    acts.querySelector('.a-cancel').onclick = () => render();
  };
  return el;
}

document.getElementById('filterZhu').onclick = e => {
  onlyZhu = !onlyZhu; e.currentTarget.classList.toggle('zhu-on', onlyZhu); render();
};
document.getElementById('q').oninput = e => { query = e.target.value; render(); };
document.getElementById('btnSnap').onclick = () => {
  location.href = '/snapshot.db' + (TOKEN ? '?token='+encodeURIComponent(TOKEN) : '');
};
document.getElementById('btnRebuild').onclick = async e => {
  e.currentTarget.disabled = true;
  try {
    const r = await (await api('/api/rebuild', {method:'POST'})).json();
    alert('索引已重建：'+r.months+' 册 · '+r.notes+' 条');
  } finally { e.currentTarget.disabled = false; }
};

loadMonths().catch(err => {
  document.getElementById('main').innerHTML =
    '<div class="empty">'+(String(err).includes('token') ? '需在网址加 ?token=…' : '连接失败：'+err.message)+'</div>';
});
</script>
</body>
</html>
"""


def main():
    if not INBOX.exists():
        print("Inbox not found: %s  (set OCR_INBOX to override)" % INBOX)
        return
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("拾字簿 serving %s" % INBOX)
    print("  local:     http://localhost:%d/" % PORT)
    print("  tailnet:   http://<mac-tailscale-name>:%d/" % PORT)
    if TOKEN:
        print("  token set: append ?token=... on the phone")
    else:
        print("  no token (tailnet-only exposure assumed); set OCR_DIARY_TOKEN to require one")
    srv.serve_forever()


if __name__ == "__main__":
    main()
