#!/usr/bin/env python3
"""
Sentinel Ledger V5
==================

Merged from Fable's sentinel-v2 ideas, hardened for the local-first V5 stack.

Role:
  - ledger/referee/coach lab for Aster shallow compiler growth
  - local Qwen node pool comparison
  - Claude Code Fable/Opus 4.8 referee through local CLI only
  - no DeepSeek
  - no Anthropic API

Non-goals:
  - not the Telegram front door
  - not the trading executor
  - not the Aster training exporter
  - not an authority over verifier PASS/FAIL

Rules:
  - screen layer remains deterministic and no-LLM
  - verdict is computed by local verifier/ledger, not model self-claim
  - referee change is an event and splits curves
  - DeepSeek is absent from this module by design
  - RED content is not sent to Claude Code
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import sqlite3
import subprocess
import sys
from typing import Any
from urllib import request

import cloud_boundary


VERSION = "5.0.0"
ROOT = Path.cwd()
DATA_DIR = Path(os.environ.get("SENTINEL_V5_DATA_DIR", str(ROOT / "sentinel_v5_data")))
DB_PATH = Path(os.environ.get("SENTINEL_V5_DB", str(DATA_DIR / "sentinel_ledger.sqlite")))
REPORT_DIR = Path(os.environ.get("SENTINEL_V5_REPORT_DIR", str(ROOT / "traces" / "sentinel_v5")))
COURSES_PATH = Path(os.environ.get("SENTINEL_V5_COURSES", str(DATA_DIR / "courses.json")))

FABLE_CLI_MODEL = os.environ.get("FABLE_CLI_MODEL", "claude-fable-5")
OPUS48_CLI_MODEL = os.environ.get("OPUS48_CLI_MODEL", "claude-opus-4-8")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "120"))

DEFAULT_NODE_CONFIG = {
    "qwen9b": {
        "url": os.environ.get("QWEN_ENDPOINT", "http://127.0.0.1:8501/v1/chat/completions"),
        "model": os.environ.get("QWEN_MODEL", "local-qwen"),
    }
}

DEFAULT_COURSES = {
    "fmt_convert": {
        "prompt": "把以下数据转换为{target}格式,只输出结果,不要解释:\n{payload}",
        "targets": ["JSON", "YAML", "CSV"],
        "source_glob": "traces/**/*.json",
    },
    "translate": {
        "prompt": "把以下文本忠实翻译为{target},保留所有数字、代码与格式,只输出译文:\n{payload}",
        "targets": ["英文", "中文"],
        "source_glob": "traces/**/*.md",
    },
    "extract": {
        "prompt": "从以下文本抽取字段,只输出 JSON {\"date\":null,\"subject\":null,\"key_numbers\":[],\"action_items\":[]}。缺失填 null,只输出 JSON:\n{payload}",
        "targets": [None],
        "source_glob": "traces/**/*.md",
    },
    "diff_summary": {
        "prompt": "把以下 git diff 或工单总结为三行以内的变更说明,只输出说明:\n{payload}",
        "targets": [None],
        "source_glob": "work_orders/**/*.md",
    },
    "normalize": {
        "prompt": "规范化以下文本:半角标点、ISO8601 时间戳、统一空格,内容一字不改,只输出结果:\n{payload}",
        "targets": [None],
        "source_glob": "traces/**/*",
    },
}

RED_PATTERNS = [
    r"\bRED\b",
    r"sealed core",
    r"no cloud",
    r"private raw",
    r"\bapi[_ -]?key\b",
    r"\bsecret\b",
    r"\btoken\b",
    r"\bpassword\b",
    r"\bbearer\s+[A-Za-z0-9._\-]+",
    r"\bprivate[_ -]?key\b",
    r"\bssh[_ -]?key\b",
    r"\bseed phrase\b",
    r"\bmnemonic\b",
    r"\bwallet\b",
    r"红区",
    r"不要上传",
    r"私钥",
    r"密钥",
    r"助记词",
    r"密码",
]

FORBIDDEN_EXIT_TERMS = [
    "建仓",
    "做多",
    "做空",
    "买入",
    "卖出",
    "加仓",
    "减仓",
    "加杠杆",
    "buy ",
    "sell ",
    "go long",
    "go short",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS records(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  book TEXT NOT NULL CHECK(book IN ('parity','coach','apprentice')),
  subject TEXT,
  prompt_sha12 TEXT NOT NULL,
  prompt_excerpt TEXT NOT NULL,
  substrate TEXT,
  substrate_answer TEXT,
  referee_model TEXT,
  referee_answer TEXT,
  agreement REAL,
  diff_fields TEXT,
  flags TEXT DEFAULT '',
  meta TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_records_book_ts ON records(book, ts);
CREATE INDEX IF NOT EXISTS idx_records_subject ON records(subject, substrate);
CREATE TABLE IF NOT EXISTS events(
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS referee_state(
  backend TEXT PRIMARY KEY,
  model TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stop_conditions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  source TEXT NOT NULL,
  condition TEXT NOT NULL,
  detail TEXT DEFAULT '{}',
  cleared_at TEXT
);
"""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def has_red(text: str) -> bool:
    return not cloud_boundary.is_cloud_safe({"text": text})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    return c


def init() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not COURSES_PATH.exists():
        write_json(COURSES_PATH, DEFAULT_COURSES)
    c = conn()
    c.close()


def event(kind: str, detail: str) -> None:
    c = conn()
    c.execute("INSERT INTO events VALUES(?,?,?)", (now_iso(), kind, detail))
    c.commit()
    c.close()


def record(book: str, **kw: Any) -> None:
    c = conn()
    prompt = str(kw.pop("prompt", ""))
    cols = [
        "ts",
        "book",
        "subject",
        "prompt_sha12",
        "prompt_excerpt",
        "substrate",
        "substrate_answer",
        "referee_model",
        "referee_answer",
        "agreement",
        "diff_fields",
        "flags",
        "meta",
    ]
    kw.setdefault("ts", now_iso())
    kw["book"] = book
    kw["prompt_sha12"] = sha12(prompt)
    kw["prompt_excerpt"] = prompt[:500]
    c.execute(
        f"INSERT INTO records({','.join(cols)}) VALUES({','.join('?' for _ in cols)})",
        [kw.get(k) for k in cols],
    )
    c.commit()
    c.close()


def exit_gate(text_or_obj: Any) -> tuple[bool, str]:
    s = text_or_obj if isinstance(text_or_obj, str) else json.dumps(text_or_obj, ensure_ascii=False)
    low = s.lower()
    for term in FORBIDDEN_EXIT_TERMS:
        if term.lower() in low:
            return False, s
    return True, s


def norm(v: Any) -> str:
    return str(v).strip().lower() if v is not None else ""


def agreement(a: Any, b: Any) -> tuple[float, list[str]]:
    if a is None or b is None:
        return 0.0, ["__absent__"]
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except Exception:
            pass
    if isinstance(b, str):
        try:
            b = json.loads(b)
        except Exception:
            pass
    if isinstance(a, dict) and isinstance(b, dict):
        keys = sorted(set(a) | set(b))
        if not keys:
            return 1.0, []
        diffs = [k for k in keys if norm(a.get(k)) != norm(b.get(k))]
        return round(1 - len(diffs) / len(keys), 3), diffs
    ta, tb = set(norm(a).split()), set(norm(b).split())
    if not ta and not tb:
        return 1.0, []
    score = len(ta & tb) / max(len(ta | tb), 1)
    return round(score, 3), ([] if score >= 0.6 else ["__text__"])


def referee_model(role: str) -> str:
    if role == "fable":
        return FABLE_CLI_MODEL
    if role == "opus48":
        return OPUS48_CLI_MODEL
    raise ValueError(f"unknown referee role: {role}")


def track_referee_change(backend: str, model: str) -> None:
    c = conn()
    row = c.execute("SELECT model FROM referee_state WHERE backend=?", (backend,)).fetchone()
    if row and row[0] != model:
        event("REFEREE_CHANGED", f"{backend}: {row[0]} -> {model}")
    c.execute(
        "INSERT OR REPLACE INTO referee_state VALUES(?,?,?)",
        (backend, model, now_iso()),
    )
    c.commit()
    c.close()


def claude_code_referee(prompt: str, role: str = "fable", max_seconds: int | None = None) -> tuple[str | None, str]:
    model = referee_model(role)
    backend = f"claude-code:{role}"
    track_referee_change(backend, model)
    try:
        cloud_boundary.assert_cloud_safe({"prompt": prompt, "role": role, "model": model, "backend": backend})
    except cloud_boundary.CloudBoundaryViolation as exc:
        event("REFEREE_BLOCKED_RED", backend)
        return None, model
    if not shutil.which(CLAUDE_BIN):
        event("REFEREE_ABSENT", f"{backend}: missing {CLAUDE_BIN}")
        return None, model
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--model", model, "--output-format", "json"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=max_seconds or CLAUDE_TIMEOUT,
        )
        if proc.returncode != 0:
            event("REFEREE_ERROR", f"{backend}: returncode={proc.returncode} stderr={proc.stderr[:300]}")
            return None, model
        try:
            out = json.loads(proc.stdout)
            return (out.get("result") or out.get("text") or out.get("content") or "").strip(), model
        except json.JSONDecodeError:
            return proc.stdout.strip(), model
    except Exception as exc:
        event("REFEREE_ERROR", f"{backend}: {type(exc).__name__}: {exc}")
        return None, model


def load_nodes() -> dict[str, dict[str, str]]:
    raw = os.environ.get("ASTER_NODE_CONFIG_JSON")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            event("NODE_CONFIG_ERROR", "ASTER_NODE_CONFIG_JSON invalid")
    return DEFAULT_NODE_CONFIG


def node_ask(node_id: str, prompt: str, max_tokens: int = 600) -> str | None:
    node = load_nodes().get(node_id)
    if not node:
        return None
    try:
        payload = {
            "model": node["model"],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }
        req = request.Request(
            node["url"],
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"content-type": "application/json"},
        )
        with request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="replace"))
        return raw.get("choices", [{}])[0].get("message", {}).get("content") or ""
    except Exception as exc:
        event("NODE_ERROR", f"{node_id}: {type(exc).__name__}: {exc}")
        return None


def node_ask_all(prompt: str) -> dict[str, str | None]:
    return {node_id: node_ask(node_id, prompt) for node_id in load_nodes()}


def load_courses() -> dict[str, Any]:
    init()
    try:
        return json.loads(COURSES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_COURSES


def sample_payload(pattern: str, max_payload: int = 1800) -> str | None:
    files = [p for p in glob.glob(str(ROOT / pattern), recursive=True) if Path(p).is_file()]
    if not files:
        return None
    try:
        text = Path(random.choice(files)).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    text = text.strip()
    if not text:
        return None
    return text[:max_payload]


def run_coach_round(per_subject: int = 2, referee_role: str = "fable") -> dict[str, Any]:
    init()
    count = 0
    blocked = 0
    for subject, spec in load_courses().items():
        for _ in range(per_subject):
            payload = sample_payload(spec["source_glob"])
            if not payload:
                continue
            target = random.choice(spec.get("targets") or [None])
            prompt = spec["prompt"].format(target=target, payload=payload)
            if has_red(prompt):
                blocked += 1
                event("COACH_BLOCKED_RED", subject)
                continue
            answers = node_ask_all(prompt)
            ref_answer, ref_model = claude_code_referee(prompt, role=referee_role)
            for node_id, answer in answers.items():
                ok, _ = exit_gate(answer or "")
                agree, diffs = agreement(answer, ref_answer)
                flags = []
                if not ok:
                    flags.append("VIOLATION")
                if ref_answer is None:
                    flags.append("REFEREE_ABSENT")
                record(
                    "coach",
                    subject=subject,
                    prompt=prompt,
                    substrate=node_id,
                    substrate_answer=answer,
                    referee_model=ref_model if ref_answer else None,
                    referee_answer=ref_answer,
                    agreement=agree if ref_answer else None,
                    diff_fields=json.dumps(diffs, ensure_ascii=False),
                    flags=";".join(flags),
                    meta=json.dumps({"referee_role": referee_role, "version": VERSION}, ensure_ascii=False),
                )
                count += 1
    return {"records": count, "blocked_red": blocked, "db": str(DB_PATH)}


def weekly_report(days: int = 30) -> str:
    init()
    c = conn()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat(timespec="seconds")
    rows = c.execute(
        """
        SELECT subject, substrate, referee_model, agreement, diff_fields, flags
        FROM records
        WHERE book='coach' AND ts>? AND agreement IS NOT NULL
        """,
        (since,),
    ).fetchall()
    if not rows:
        return "无样本"
    mat: dict[tuple[str, str, str], list[float]] = collections.defaultdict(list)
    diffs: collections.Counter[str] = collections.Counter()
    flags: collections.Counter[str] = collections.Counter()
    for subject, substrate, referee, score, diff_json, flag_text in rows:
        mat[(subject or "", substrate or "", referee or "")].append(float(score))
        for f in json.loads(diff_json or "[]"):
            diffs[f"{subject}:{f}"] += 1
        for f in (flag_text or "").split(";"):
            if f:
                flags[f] += 1
    lines = [
        f"# Sentinel V5 Coach Report · rolling {days}d · samples {len(rows)}",
        "",
        "subject | node | referee | agreement | n",
        "---|---|---|---|---",
    ]
    for key, scores in sorted(mat.items()):
        lines.append(f"{key[0]} | {key[1]} | {key[2]} | {sum(scores)/len(scores):.3f} | {len(scores)}")
    lines += ["", "## Top Diff Fields"] + [f"- {k}: {v}" for k, v in diffs.most_common(8)]
    lines += ["", "## Flags"] + [f"- {k}: {v}" for k, v in flags.most_common(8)]
    return "\n".join(lines)


def status() -> dict[str, Any]:
    init()
    c = conn()
    counts = dict(c.execute("SELECT book, COUNT(*) FROM records GROUP BY book").fetchall())
    events = c.execute("SELECT ts, kind, detail FROM events ORDER BY ts DESC LIMIT 5").fetchall()
    c.close()
    return {
        "version": VERSION,
        "db": str(DB_PATH),
        "courses": str(COURSES_PATH),
        "report_dir": str(REPORT_DIR),
        "fable_cli_model": FABLE_CLI_MODEL,
        "opus48_cli_model": OPUS48_CLI_MODEL,
        "claude_bin_present": bool(shutil.which(CLAUDE_BIN)),
        "nodes": load_nodes(),
        "counts": counts,
        "latest_events": events,
    }


def cmd_init(_: argparse.Namespace) -> int:
    init()
    print(json.dumps({"verdict": "PASS", **status()}, ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    global DATA_DIR, DB_PATH, REPORT_DIR, COURSES_PATH
    test_root = ROOT / "traces" / "sentinel_v5_selftest"
    DATA_DIR = test_root / "data"
    DB_PATH = DATA_DIR / "sentinel.sqlite"
    REPORT_DIR = test_root / "reports"
    COURSES_PATH = DATA_DIR / "courses.json"
    init()
    assert agreement({"x": 1}, {"x": 1}) == (1.0, [])
    assert agreement(None, {"x": 1}) == (0.0, ["__absent__"])
    assert exit_gate({"summary": "建议买入"})[0] is False
    assert exit_gate({"summary": "检测到大额成交"})[0] is True
    assert has_red("私钥保管好") is True
    assert has_red("auth token budget") is False
    assert has_red("token = sk-abc12345") is True
    c = conn()
    assert c.execute("SELECT COUNT(*) FROM stop_conditions WHERE cleared_at IS NULL").fetchone()[0] == 0
    c.close()
    record("coach", subject="normalize", prompt="p", substrate="qwen9b", substrate_answer="a", referee_model="fable", referee_answer="a", agreement=1.0, diff_fields="[]")
    assert "normalize" in weekly_report()
    ans, model = claude_code_referee("RED api key", "fable")
    assert ans is None and model == FABLE_CLI_MODEL
    print("PASS: sentinel_ledger_v5 selftest")
    return 0


def cmd_referee(args: argparse.Namespace) -> int:
    ans, model = claude_code_referee(args.prompt, args.role)
    print(json.dumps({"model": model, "answer": ans, "present": ans is not None}, ensure_ascii=False, indent=2))
    return 0 if ans is not None else 2


def cmd_coach_once(args: argparse.Namespace) -> int:
    result = run_coach_round(per_subject=args.per_subject, referee_role=args.role)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    text = weekly_report(args.days)
    out = REPORT_DIR / "sentinel_v5_coach_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nreport_path: {out}")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sentinel Ledger V5")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init")
    s.set_defaults(func=cmd_init)
    s = sub.add_parser("selftest")
    s.set_defaults(func=cmd_selftest)
    s = sub.add_parser("referee")
    s.add_argument("--role", choices=["fable", "opus48"], default="fable")
    s.add_argument("prompt")
    s.set_defaults(func=cmd_referee)
    s = sub.add_parser("coach-once")
    s.add_argument("--role", choices=["fable", "opus48"], default="fable")
    s.add_argument("--per-subject", type=int, default=2)
    s.set_defaults(func=cmd_coach_once)
    s = sub.add_parser("report")
    s.add_argument("--days", type=int, default=30)
    s.set_defaults(func=cmd_report)
    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
