#!/usr/bin/env python3
"""H1 carrier: read 8501 store field-particle (ro), move ```job blocks to 8630. No summarize."""
from __future__ import annotations
import hashlib, json, os, re, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEMO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from harness.ops import parse_action_plan
STATE = ROOT / "state"
SEEN = STATE / "h1_seen.json"
PENDING = STATE / "h1_pending.jsonl"
OUTBOX = STATE / "h1_outbox.jsonl"
STORE_NODE = "field-particle"
STORE_URL = os.environ.get("H1_STORE_URL", "http://127.0.0.1:8501/store/conversations/field-particle")
JOBS_URL = os.environ.get("H1_JOBS_URL", "http://127.0.0.1:8630/api/jobs")
MISSIONS_URL = os.environ.get("H1_MISSIONS_URL", "http://127.0.0.1:8630/api/missions")
INTERVAL = float(os.environ.get("H1_INTERVAL_SEC", "5"))
JOB_RE = re.compile(r"```job\s*\n(.*?)```", re.S)


def _load_env() -> None:
    p = Path.home() / ".config" / "grid" / "harness_resident.env"
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _redact(s: str) -> str:
    return re.sub(r"(Bearer\s+)\S+", r"\1[redacted]", str(s))


def _log(msg: str) -> None:
    print(_redact(msg), flush=True)


def sha3_hex(s: str) -> str:
    return hashlib.sha3_256(s.encode("utf-8")).hexdigest()


def idem_key(ctx: str, block: str) -> str:
    return sha3_hex((ctx or "") + block)


def load_seen() -> set[str]:
    if not SEEN.is_file():
        return set()
    try:
        data = json.loads(SEEN.read_text(encoding="utf-8"))
        return set(data if isinstance(data, list) else data.get("keys") or [])
    except json.JSONDecodeError:
        return set()


def save_seen(keys: set[str]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    SEEN.write_text(json.dumps(sorted(keys)), encoding="utf-8")


def append_jsonl(path: Path, row: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_block(body: str) -> dict:
    text = body.strip()
    typ = ""
    ctx = ""
    m = re.search(r"type:\s*(\S+)", text)
    if m:
        typ = m.group(1).strip().strip('"').strip("'")
    m = re.search(r"context_hash:\s*(\S+)", text)
    if m:
        ctx = m.group(1).strip().strip('"').strip("'")
        if ctx in {"<door_computed>", "<hash>", "null"}:
            ctx = ""
    steps = parse_action_plan(text)
    return {"type": typ, "context_hash": ctx, "steps": steps, "body": text}


def extract_jobs(messages: list) -> list[dict]:
    out = []
    for msg in messages or []:
        if str(msg.get("role") or "") != "assistant":
            continue
        content = str(msg.get("content") or "")
        for m in JOB_RE.finditer(content):
            block = m.group(1)
            parsed = parse_block(block)
            parsed["raw"] = m.group(0)
            out.append(parsed)
    return out


def fetch_store() -> list:
    req = urllib.request.Request(f"{STORE_URL}?limit=80", method="GET")
    token = os.environ.get("GRID_STORE_TOKEN") or os.environ.get("GRID_GATEWAY_TOKEN") or ""
    if token:
        req.add_header("X-Grid-Token", token)
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        _log(f"store_ro_fail {type(exc).__name__}")
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        msgs = raw.get("messages")
        if isinstance(msgs, list):
            return msgs
    return []


def post_job(parsed: dict) -> tuple[bool, str]:
    token = (os.environ.get("GRID_HARNESS_H1_TOKEN") or os.environ.get("GRID_HARNESS_TOKEN") or "").strip()
    payload = {
        "content": parsed["raw"],
        "origin": "grid_compiled",
        "context_hash": parsed["context_hash"],
        "steps": parsed["steps"],
        "read_only": True,
        "worker": "cc",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(JOBS_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return True, body
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, "unreachable"


def _mission_budget_from_block(block: str) -> dict:
    """Parse a ```job block of type MISSION into a /api/missions payload.
    Budget defaults to 1/10 of config upper (Grid 9-08 G rule). The block may
    override goal/lane/worker/budget_hops/budget_usd/stop_conditions."""
    typ = ""
    goal = ""
    lane = "scout"
    worker = "deep"
    budget_hops = 30
    budget_usd = 1.0
    stop = []
    for line in block.splitlines():
        s = line.strip()
        if s.startswith("type:"):
            typ = s.split(":", 1)[1].strip().strip('"').strip("'")
        elif s.startswith("goal:") or s.startswith("mission:"):
            goal = s.split(":", 1)[1].strip().strip('"').strip("'")
        elif s.startswith("lane:"):
            lane = s.split(":", 1)[1].strip().strip('"').strip("'")
        elif s.startswith("worker:"):
            worker = s.split(":", 1)[1].strip().strip('"').strip("'")
        elif s.startswith("budget_hops:"):
            try: budget_hops = int(s.split(":", 1)[1].strip())
            except ValueError: pass
        elif s.startswith("budget_usd:"):
            try: budget_usd = float(s.split(":", 1)[1].strip())
            except ValueError: pass
        elif s.startswith("stop:"):
            stop.append(s.split(":", 1)[1].strip().strip('"').strip("'"))
    return {
        "goal": goal or "(no goal in block)",
        "lane": lane, "worker": worker,
        "budget_hops": max(1, budget_hops // 10),
        "budget_usd": round(budget_usd / 10, 4),
        "stop_conditions": stop,
        "created_by": "grid_compiled",
        "status": "proposed",
    }


def post_mission(parsed: dict) -> tuple[bool, str]:
    """H1 分路 ③: type MISSION -> POST /api/missions (proposed, no job runs until Lyra 放行)."""
    token = (os.environ.get("GRID_HARNESS_TOKEN") or "").strip()
    body = _mission_budget_from_block(parsed.get("body") or "")
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(MISSIONS_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, "unreachable"


def handle(parsed: dict, seen: set[str]) -> str:
    ctx = parsed.get("context_hash") or ""
    key = idem_key(ctx, parsed["raw"])
    if key in seen:
        return "idem"
    typ = str(parsed.get("type") or "").upper()
    row = {"ts": time.time(), "key": key, "type": typ, "context_hash": ctx, "node": STORE_NODE}
    if typ == "MISSION":
        ok, body = post_mission(parsed)
        append_jsonl(OUTBOX, {**row, "kind": "mission_seed" if ok else "mission_seed_fail",
                              "ok": ok, "resp": body[:400]})
        seen.add(key)
        save_seen(seen)
        return "mission_seed" if ok else "mission_seed_fail"
    if typ in {"QUERY", "STATE"}:
        append_jsonl(OUTBOX, {**row, "kind": "outbox", "raw": parsed["raw"]})
        seen.add(key)
        save_seen(seen)
        return "outbox"
    if not ctx:
        append_jsonl(PENDING, {**row, "kind": "NO_CTX", "raw": parsed["raw"]})
        seen.add(key)
        save_seen(seen)
        return "NO_CTX"
    # Generated fenced job text alone must not submit. Confirm path is 8630 /compile/confirm.
    append_jsonl(OUTBOX, {**row, "kind": "ignored_fence"})
    seen.add(key)
    save_seen(seen)
    return "ignored_fence"


def scan_once() -> list[str]:
    seen = load_seen()
    msgs = fetch_store()
    if not SEEN.is_file():
        for parsed in extract_jobs(msgs):
            ctx = parsed.get("context_hash") or ""
            seen.add(idem_key(ctx, parsed["raw"]))
        save_seen(seen)
        _log(f"bootstrap_seen {len(seen)}")
        return ["bootstrap"]
    results = []
    for parsed in extract_jobs(msgs):
        results.append(handle(parsed, seen))
    return results


def selftest() -> int:
    global STATE, SEEN, PENDING, OUTBOX
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="h1self_"))
    STATE, SEEN, PENDING, OUTBOX = tmp, tmp / "seen.json", tmp / "pending.jsonl", tmp / "outbox.jsonl"
    seen: set[str] = set()
    action = parse_block("intent:\n  type: ACTION\n  context_hash: abc\n  action_plan:\n    - op: FS_STAT\n      target: harness_resident/harness\n")
    action["raw"] = "```job\n" + action["body"] + "\n```"
    q = parse_block("intent:\n  type: QUERY\n  context_hash: abc\n")
    q["raw"] = "```job\n" + q["body"] + "\n```"
    no = parse_block("intent:\n  type: ACTION\n  action_plan:\n    - op: FS_STAT\n")
    no["raw"] = "```job\n" + no["body"] + "\n```"
    assert handle(q, seen) == "outbox"
    assert handle(no, seen) == "NO_CTX"
    assert handle(q, seen) == "idem"
    user_only = extract_jobs([{"role": "user", "content": action["raw"]}])
    assert user_only == []
    asst = extract_jobs([{"role": "assistant", "content": action["raw"]}])
    assert len(asst) == 1 and asst[0]["steps"][0]["op"] == "FS_STAT"
    assert asst[0]["steps"][0].get("target") == "harness_resident/harness"
    k1 = idem_key("h", "block")
    k2 = idem_key("h", "block2")
    k3 = idem_key("h2", "block")
    assert k1 != k2 and k1 != k3
    print("h1_selftest GREEN", flush=True)
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    _load_env()
    _log("h1_carrier start node=field-particle mode=ro")
    while True:
        try:
            scan_once()
        except Exception as exc:
            _log(f"scan_err {type(exc).__name__}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
