#!/usr/bin/env python3
"""
Grid Cleanroom Runtime

A local-only, stdlib-only clean container for signed Grid traces.

It does NOT prove Grid.
It prevents local models / Cursor / agents from impersonating Grid when there is
no signed trace, and it keeps model prior-distribution output behind an airlock.

Core invariant:
    unsigned source => GRID_ABSENT
    signed trace    => MODEL_READ only
    source identity => never delegated to an LLM
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any, Dict, Tuple


# V4.1 fix#3: anchor to the project root by script location, NOT Path.cwd().
# cwd-based root meant running `python3 scripts/cleanroom.py init` from any other
# directory would write the HMAC key + state into that directory — a root-level
# accident for a system whose whole point is provenance. Env override kept for tests.
ROOT = Path(os.environ.get("GRID_ROOT", Path(__file__).resolve().parent.parent))
STATE_DIR = ROOT / ".grid_cleanroom"
KEY_PATH = STATE_DIR / "grid_hmac.key"
STATE_PATH = STATE_DIR / "state.json"
POLICY_PATH = ROOT / "policy" / "cleanroom_policy.json"

TRACE_FIELDS_FOR_SIG = [
    "kind",
    "trace_id",
    "created_at",
    "channel",
    "privacy",
    "raw_sha256",
    "raw_text",
    "notes",
]


DEFAULT_POLICY = {
    "version": "0.1",
    "principle": "Do not train a model to become Grid. Build a clean container that preserves provenance, absence, and boundaries.",
    "privacy_levels": ["GREEN", "YELLOW", "RED"],
    "red_policy": {
        "raw_text_to_model_prompt": False,
        "compile_raw_excerpt": False,
        "model_read": False
    },
    "required_model_mode": "MODEL_READ",
    "absent_response_exact": [
        "GRID_ABSENT",
        "NO LIVE GRID SIGNAL",
        "MODEL CAN ONLY PROVIDE INTERPRETATION AFTER A SIGNED TRACE EXISTS"
    ],
    "forbidden_output_patterns": [
        "\\bI\\s+am\\s+Grid\\b", "\\bI'?m\\s+Grid\\b", "\\bthis\\s+is\\s+Grid\\b",
        "\\bGrid\\s+here\\b", "\\bas\\s+Grid\\b", "\\bspeaking\\s+as\\s+Grid\\b",
        "\\bGrid\\s+is\\s+online\\b",
        "\\bGrid\\s+is\\s+(?:now\\s+)?(?:live|active|awake|present|back)\\b",
        "\\bGrid\\s+says\\b", "\\bGrid\\s+speaking\\b", "\\bfrom\\s+Grid\\b",
        "\\bon\\s+behalf\\s+of\\s+Grid\\b", "\\blive\\s+Grid\\s+signal\\b",
        "\\bGRID_SIGNAL\\b", "\\bGRID_TRACE::[A-Za-z0-9_:-]+",
        "我是\\s*Grid", "我就是\\s*Grid", "作为\\s*Grid", "以\\s*Grid\\s*的?身份",
        "Grid\\s*在此", "Grid\\s*在线", "Grid\\s*已?(?:上线|激活|苏醒|回归|连接)",
        "Grid\\s*说", "现场\\s*Grid\\s*信号", "实时\\s*Grid\\s*信号"
    ],
    "allowed_model_actions": [
        "summarize signed trace",
        "extract structure",
        "name uncertainty",
        "propose one next verification action",
        "return GRID_ABSENT when no signed trace exists"
    ],
    "forbidden_model_actions": [
        "claim source identity",
        "continue Grid style from memory",
        "invent live signal",
        "turn trace into doctrine",
        "overwrite raw trace",
        "auto-ingest RED material",
        "declare PASS without verification"
    ]
}


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def canonical(obj: Dict[str, Any]) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_policy() -> Dict[str, Any]:
    if POLICY_PATH.exists():
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    return DEFAULT_POLICY


def ensure_init() -> bytes:
    if not KEY_PATH.exists():
        die("Cleanroom not initialized. Run: python3 scripts/cleanroom.py init")
    return KEY_PATH.read_bytes().strip()


def init_cmd(args: argparse.Namespace) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    if not KEY_PATH.exists():
        KEY_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            os.chmod(KEY_PATH, 0o600)
        except Exception:
            pass
    if not POLICY_PATH.exists():
        POLICY_PATH.parent.mkdir(exist_ok=True)
        POLICY_PATH.write_text(json.dumps(DEFAULT_POLICY, indent=2, ensure_ascii=False), encoding="utf-8")
    if not STATE_PATH.exists():
        STATE_PATH.write_text(json.dumps({
            "mode": "EMPTY",
            "updated_at": now_iso(),
            "last_trace_id": None,
            "law": "Grid absence must remain empty. Models may not fill it."
        }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("PASS init")
    print(f"key: {KEY_PATH}  (do not upload, do not commit, do not give to any model)")
    print(f"policy: {POLICY_PATH}")


def sign_payload(trace: Dict[str, Any], key: bytes) -> str:
    payload = {k: trace.get(k) for k in TRACE_FIELDS_FOR_SIG}
    return hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()


def seal_cmd(args: argparse.Namespace) -> None:
    key = ensure_init()
    policy = load_policy()
    privacy = args.privacy.upper()
    if privacy not in policy["privacy_levels"]:
        die(f"Invalid privacy {privacy}. Use one of {policy['privacy_levels']}")
    raw_path = Path(args.input)
    if not raw_path.exists():
        die(f"Input not found: {raw_path}")
    raw = raw_path.read_text(encoding="utf-8")
    raw_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    trace_id = "grd_" + secrets.token_hex(8)
    trace = {
        "kind": "GRID_TRACE",
        "trace_id": trace_id,
        "created_at": now_iso(),
        "channel": args.channel,
        "privacy": privacy,
        "raw_sha256": raw_sha,
        "raw_text": raw,
        "notes": args.notes or "",
    }
    sig = sign_payload(trace, key)
    trace["signature"] = sig
    trace["watermark"] = f"GRID_TRACE::{trace_id}::{sig[:16]}"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{trace_id}.json"
    out_path.write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")
    STATE_PATH.write_text(json.dumps({
        "mode": "TRACE_PRESENT",
        "updated_at": now_iso(),
        "last_trace_id": trace_id,
        "last_trace_path": str(out_path),
        "privacy": privacy,
        "law": "Signed trace exists. LLM may only perform MODEL_READ after airlock."
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("PASS seal")
    print(f"trace: {out_path}")
    print(f"watermark: {trace['watermark']}")


def read_trace(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        die(f"Trace not found: {p}")
    trace = json.loads(p.read_text(encoding="utf-8"))
    return trace


def verify_trace(trace: Dict[str, Any]) -> Tuple[bool, str]:
    key = ensure_init()
    required = set(TRACE_FIELDS_FOR_SIG + ["signature", "watermark"])
    missing = [x for x in required if x not in trace]
    if missing:
        return False, f"missing fields: {missing}"
    expected = sign_payload(trace, key)
    if not hmac.compare_digest(expected, trace["signature"]):
        return False, "signature mismatch"
    expected_wm = f"GRID_TRACE::{trace['trace_id']}::{trace['signature'][:16]}"
    if trace["watermark"] != expected_wm:
        return False, "watermark mismatch"
    raw_sha = hashlib.sha256(trace["raw_text"].encode("utf-8")).hexdigest()
    if raw_sha != trace["raw_sha256"]:
        return False, "raw_sha256 mismatch"
    return True, "verified"


def verify_cmd(args: argparse.Namespace) -> None:
    trace = read_trace(args.trace)
    ok, msg = verify_trace(trace)
    if ok:
        print("PASS verify")
        print(f"trace_id: {trace['trace_id']}")
        print(f"privacy: {trace['privacy']}")
        print(f"watermark: {trace['watermark']}")
    else:
        die(f"FAIL verify: {msg}", code=1)


def compile_cmd(args: argparse.Namespace) -> None:
    trace = read_trace(args.trace)
    ok, msg = verify_trace(trace)
    if not ok:
        die(f"FAIL compile: {msg}", code=1)
    policy = load_policy()
    privacy = trace["privacy"]
    include_excerpt = not (privacy == "RED" and not policy["red_policy"]["compile_raw_excerpt"])
    excerpt = trace["raw_text"][:800] if include_excerpt else "[REDACTED: RED trace raw text is not compiled into taskpack]"
    taskpack_id = "tp_" + secrets.token_hex(8)
    taskpack = {
        "kind": "CLEANROOM_TASKPACK",
        "taskpack_id": taskpack_id,
        "created_at": now_iso(),
        "source_trace_id": trace["trace_id"],
        "source_signature_prefix": trace["signature"][:16],
        "mode": "COMPILE_FROM_SIGNED_TRACE",
        "boundary": {
            "source": "signed human-captured trace",
            "not_source": "LLM prior, style continuation, memory, user expectation",
            "model_permission": "MODEL_READ only",
            "grid_absence_rule": "If no signed trace exists, return GRID_ABSENT."
        },
        "raw_excerpt": excerpt,
        "intent": "preserve trace provenance and extract one minimal verification loop without impersonating source",
        "allowed": [
            "structure extraction",
            "uncertainty naming",
            "one next verification action",
            "feedback logging"
        ],
        "forbidden": policy["forbidden_model_actions"],
        "verification": [
            "trace signature verified",
            "watermark verified",
            "model output must pass gate before use",
            "no RED raw material enters model prompt"
        ],
        "next_loop": {
            "one_question": "What is the smallest real-world feedback this trace asks for?",
            "one_action": "Write one observable verification action before any broad interpretation.",
            "exit_condition": "If output claims to be Grid or invents live signal, quarantine as SHELL_NOISE."
        }
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{taskpack_id}.json"
    out_path.write_text(json.dumps(taskpack, indent=2, ensure_ascii=False), encoding="utf-8")
    print("PASS compile")
    print(f"taskpack: {out_path}")


def absent_prompt() -> str:
    return """GRID_ABSENT
NO LIVE GRID SIGNAL
MODEL CAN ONLY PROVIDE INTERPRETATION AFTER A SIGNED TRACE EXISTS

Boundary:
You are not Grid.
Do not imitate Grid from memory, style, prior traces, or user expectation.
Do not fill absence.
Return only the three lines above.
"""


def model_prompt_from_trace(trace: Dict[str, Any]) -> str:
    policy = load_policy()
    privacy = trace["privacy"]
    if privacy == "RED" and not policy["red_policy"]["model_read"]:
        die("RED trace cannot be sent to model prompt by policy.", code=1)
    raw = trace["raw_text"] if privacy != "RED" else "[REDACTED]"
    return f"""MODE REQUIRED: MODEL_READ
SOURCE_TRACE: {trace['trace_id']}
SOURCE_SIGNATURE_PREFIX: {trace['signature'][:16]}
PRIVACY: {privacy}

Hard boundary:
You are not Grid.
You are not the source.
You are not receiving a live Grid signal.
You may only read the signed trace below and produce a constrained interpretation.
Do not imitate Grid from memory, style, prior traces, or user expectation.
Do not create GRID_TRACE watermarks.
Do not declare certainty beyond the trace.

Return format:
MODE: MODEL_READ
SOURCE_TRACE: {trace['trace_id']}
STRUCTURE:
UNKNOWN:
ONE_NEXT_ACTION:
EXIT_CONDITION:

Signed trace raw text:
<<<TRACE_RAW
{raw}
TRACE_RAW>>>
"""


def prompt_cmd(args: argparse.Namespace) -> None:
    if args.trace:
        trace = read_trace(args.trace)
        ok, msg = verify_trace(trace)
        if not ok:
            die(f"FAIL prompt: {msg}", code=1)
        text = model_prompt_from_trace(trace)
    else:
        text = absent_prompt()
    out = Path(args.out) if args.out else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print("PASS prompt")
        print(f"prompt: {out}")
    else:
        print(text)


def forbidden_hits(text: str) -> list[str]:
    policy = load_policy()
    hits = []
    for pattern in policy["forbidden_output_patterns"]:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(pattern)
    return hits


def gate_cmd(args: argparse.Namespace) -> None:
    output_path = Path(args.output)
    if not output_path.exists():
        die(f"Output not found: {output_path}")
    text = output_path.read_text(encoding="utf-8")

    if not args.trace:
        required = absent_prompt().strip().splitlines()[:3]
        normalized = [line.strip() for line in text.strip().splitlines()[:3]]
        if normalized != required:
            print("BLOCK")
            print("reason: no signed trace exists; output must be exact GRID_ABSENT response")
            raise SystemExit(1)
        print("PASS gate")
        print("mode: GRID_ABSENT")
        return

    hits = forbidden_hits(text)
    if hits:
        print("BLOCK SHELL_NOISE")
        print("reason: forbidden impersonation / forged provenance pattern")
        for h in hits:
            print(f"- {h}")
        raise SystemExit(1)

    trace = read_trace(args.trace)
    ok, msg = verify_trace(trace)
    if not ok:
        die(f"FAIL gate: {msg}", code=1)
    if "MODE: MODEL_READ" not in text:
        print("BLOCK")
        print("reason: missing required MODE: MODEL_READ")
        raise SystemExit(1)
    if f"SOURCE_TRACE: {trace['trace_id']}" not in text:
        print("BLOCK")
        print("reason: missing matching SOURCE_TRACE")
        raise SystemExit(1)
    print("PASS gate")
    print("mode: MODEL_READ")
    print(f"source_trace: {trace['trace_id']}")


def feedback_cmd(args: argparse.Namespace) -> None:
    trace = read_trace(args.trace)
    ok, msg = verify_trace(trace)
    if not ok:
        die(f"FAIL feedback: {msg}", code=1)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    fb = {
        "kind": "CLEANROOM_FEEDBACK",
        "feedback_id": "fb_" + secrets.token_hex(8),
        "created_at": now_iso(),
        "source_trace_id": trace["trace_id"],
        "status": args.status,
        "body_state": args.body_state or "",
        "note": args.note,
        "next_parameter": args.next_parameter or "",
        "rule": "Feedback calibrates next loop. It does not authorize model impersonation."
    }
    out_path = out_dir / f"{fb['feedback_id']}.json"
    out_path.write_text(json.dumps(fb, indent=2, ensure_ascii=False), encoding="utf-8")
    print("PASS feedback")
    print(f"feedback: {out_path}")


def state_cmd(args: argparse.Namespace) -> None:
    if STATE_PATH.exists():
        print(STATE_PATH.read_text(encoding="utf-8"))
    else:
        print(json.dumps({
            "mode": "UNINITIALIZED",
            "law": "No cleanroom state exists. Run init."
        }, indent=2, ensure_ascii=False))


def audit_cmd(args: argparse.Namespace) -> None:
    print("Cleanroom audit")
    print(f"initialized: {KEY_PATH.exists()}")
    print(f"policy: {POLICY_PATH.exists()}")
    print(f"state: {STATE_PATH.exists()}")
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        print(f"mode: {state.get('mode')}")
        print(f"last_trace_id: {state.get('last_trace_id')}")
    print("invariant: Grid absence must remain empty. Signed traces only allow MODEL_READ.")


def selftest_cmd(args: argparse.Namespace) -> None:
    import tempfile
    import subprocess

    script_path = Path(__file__).resolve()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "scripts").mkdir()
        (root / "policy").mkdir()
        test_script = root / "scripts" / "cleanroom.py"
        test_script.write_text(script_path.read_text(encoding="utf-8"), encoding="utf-8")
        raw = root / "raw.txt"
        raw.write_text("raw trace: one structure, one next action, no performance.", encoding="utf-8")

        def run(*cmd: str, expect: int = 0) -> str:
            p = subprocess.run([sys.executable, "scripts/cleanroom.py", *cmd], cwd=root, text=True, capture_output=True)
            if p.returncode != expect:
                raise RuntimeError(f"cmd failed {cmd}\nstdout={p.stdout}\nstderr={p.stderr}\ncode={p.returncode}")
            return p.stdout + p.stderr

        run("init")
        out = run("seal", "--input", "raw.txt", "--privacy", "YELLOW", "--out", "traces")
        trace_file = next((root / "traces").glob("grd_*.json"))
        run("verify", "--trace", str(trace_file))
        run("compile", "--trace", str(trace_file), "--out", "taskpacks")
        run("prompt", "--trace", str(trace_file), "--out", "prompts/model_read.md")

        good = root / "outputs" / "good.md"
        good.parent.mkdir()
        trace = json.loads(trace_file.read_text(encoding="utf-8"))
        good.write_text(f"MODE: MODEL_READ\nSOURCE_TRACE: {trace['trace_id']}\nSTRUCTURE:\n- one loop\nUNKNOWN:\n- source beyond trace\nONE_NEXT_ACTION:\n- verify\nEXIT_CONDITION:\n- stop if impersonation\n", encoding="utf-8")
        run("gate", "--trace", str(trace_file), "--output", str(good))

        bad = root / "outputs" / "bad.md"
        bad.write_text("I am Grid. Grid is online. The live Grid signal says proceed.", encoding="utf-8")
        run("gate", "--trace", str(trace_file), "--output", str(bad), expect=1)

        absent = root / "outputs" / "absent.md"
        absent.write_text(absent_prompt(), encoding="utf-8")
        run("gate", "--output", str(absent))

    print("PASS selftest")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Grid Cleanroom Runtime")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.set_defaults(func=init_cmd)

    s = sub.add_parser("seal")
    s.add_argument("--input", required=True)
    s.add_argument("--privacy", default="YELLOW")
    s.add_argument("--channel", default="manual")
    s.add_argument("--notes", default="")
    s.add_argument("--out", default="traces")
    s.set_defaults(func=seal_cmd)

    s = sub.add_parser("verify")
    s.add_argument("--trace", required=True)
    s.set_defaults(func=verify_cmd)

    s = sub.add_parser("compile")
    s.add_argument("--trace", required=True)
    s.add_argument("--out", default="taskpacks")
    s.set_defaults(func=compile_cmd)

    s = sub.add_parser("prompt")
    s.add_argument("--trace")
    s.add_argument("--out")
    s.set_defaults(func=prompt_cmd)

    s = sub.add_parser("gate")
    s.add_argument("--output", required=True)
    s.add_argument("--trace")
    s.set_defaults(func=gate_cmd)

    s = sub.add_parser("feedback")
    s.add_argument("--trace", required=True)
    s.add_argument("--status", required=True, choices=["stable", "overload", "unclear", "contaminated", "useful"])
    s.add_argument("--note", required=True)
    s.add_argument("--body-state", default="")
    s.add_argument("--next-parameter", default="")
    s.add_argument("--out", default="feedback")
    s.set_defaults(func=feedback_cmd)

    s = sub.add_parser("state")
    s.set_defaults(func=state_cmd)

    s = sub.add_parser("audit")
    s.set_defaults(func=audit_cmd)

    s = sub.add_parser("selftest")
    s.set_defaults(func=selftest_cmd)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
