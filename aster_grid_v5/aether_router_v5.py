#!/usr/bin/env python3
"""
Aether Router V5
================

No DeepSeek. No Anthropic API.

Purpose:
  - route Aether/Aster tasks locally
  - keep screen layer deterministic and no-LLM
  - use Claude Code Opus 4.8/Fable only as local CLI referee/reviewer
  - keep DeepSeek artifacts blocklisted from Aster learning

Model authority:
  - screen: no LLM
  - quant/stat/decision audit: Claude Code Opus 4.8
  - compile/architecture/promotion: Claude Code Fable
  - RED: local only
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

import cloud_boundary
import provenance_registry

try:
    import sentinel_ledger_v5 as sentinel
except Exception:
    sentinel = None


VERSION = "5.0.0"
ROOT = Path.cwd()
DATA_DIR = Path(os.environ.get("AETHER_ROUTER_DATA_DIR", str(ROOT / "aether_router_v5_data")))
DB_PATH = DATA_DIR / "aether_router_v5.sqlite"
PROOF_DIR = ROOT / "traces" / "aether_router_v5"
SCREEN_DIR = DATA_DIR / "deterministic_screen"
LEARNING_BLOCKLIST = Path(os.environ.get("ASTER_LEARNING_BLOCKLIST", str(DATA_DIR / "aster_learning_blocklist.jsonl")))


SCHEMA = """
CREATE TABLE IF NOT EXISTS calls(
  id TEXT PRIMARY KEY,
  created_at TEXT,
  route TEXT,
  task_kind TEXT,
  risk TEXT,
  reviewer TEXT,
  learning_allowed INTEGER,
  prompt_sha12 TEXT,
  response_sha12 TEXT,
  status TEXT,
  artifact_path TEXT
);
"""

RED_TERMS = [
    "red",
    "sealed",
    "no cloud",
    "private raw",
    "api key",
    "secret",
    "token",
    "password",
    "private key",
    "ssh key",
    "seed phrase",
    "mnemonic",
    "wallet",
    "红区",
    "私钥",
    "密钥",
    "助记词",
    "密码",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def log_call(row: dict[str, Any]) -> None:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["id"],
            row["created_at"],
            row.get("route"),
            row.get("task_kind"),
            row.get("risk"),
            row.get("reviewer"),
            1 if row.get("learning_allowed") else 0,
            row.get("prompt_sha12"),
            row.get("response_sha12"),
            row.get("status"),
            row.get("artifact_path"),
        ),
    )
    conn.commit()
    conn.close()


def classify(text: str) -> dict[str, str]:
    low = text.lower()
    risk = "RED" if not cloud_boundary.is_cloud_safe({"text": text}) else "GREEN"
    if risk != "RED" and any(t in low for t in ["grid", "aster", "jarvis", "sudo", "permission", "权限"]):
        risk = "YELLOW"

    if any(t in low for t in ["compile", "compiler", "verdict", "promotion", "jarvis brain", "架构", "编译"]):
        task_kind = "compiler_architecture"
    elif any(t in low for t in ["decision", "should we", "建仓", "做多", "做空", "buy", "sell", "trade decision", "交易决策"]):
        task_kind = "decision_audit"
    elif any(t in low for t in ["backtest", "t-test", "bootstrap", "opex", "theta", "quant", "回测", "统计"]):
        task_kind = "quant_review"
    elif any(t in low for t in ["shortlist", "rank", "ranking", "候选", "排序"]):
        task_kind = "screen_rank"
    elif any(t in low for t in ["option", "options", "crypto", "screen", "scan", "watchlist", "aether daily", "筛选", "扫描"]):
        task_kind = "daily_screen"
    elif any(t in low for t in ["backend", "api", "state machine", "daemon", "queue", "cursor", "deploy"]):
        task_kind = "backend_engineering"
    else:
        task_kind = "general"
    return {"risk": risk, "task_kind": task_kind}


def choose_route(text: str) -> dict[str, Any]:
    meta = classify(text)
    if meta["risk"] == "RED":
        return {"route": "local_only", "reviewer": None, "learning_allowed": False, **meta}
    if meta["task_kind"] in {"daily_screen", "screen_rank"}:
        return {
            "route": "deterministic_screen_no_llm",
            "reviewer": None,
            "learning_allowed": False,
            "no_order_execution": True,
            **meta,
        }
    if meta["task_kind"] in {"quant_review", "decision_audit", "backend_engineering", "general"}:
        return {"route": "claude_code_opus48", "reviewer": "opus48", "learning_allowed": False, **meta}
    if meta["task_kind"] == "compiler_architecture":
        return {"route": "claude_code_fable", "reviewer": "fable", "learning_allowed": True, **meta}
    return {"route": "local_only", "reviewer": None, "learning_allowed": False, **meta}


def deterministic_screen_artifact(prompt: str, route: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "deterministic_screen_no_llm",
        "created_at": now_iso(),
        "prompt_sha12": sha12(prompt),
        "route": route,
        "no_order_execution": True,
        "learning_allowed": False,
        "screen_status": "ROUTED_ONLY",
        "next_required": "Aether scanner must compute candidates from market data; no LLM screen allowed in V5",
    }


def call_route(prompt: str) -> dict[str, Any]:
    init_db()
    route = choose_route(prompt)
    run_id = "aether_v5_" + sha12(f"{now_iso()}|{prompt}|{json.dumps(route, sort_keys=True)}")

    if route["route"] == "local_only":
        result = {"status": "local_only", "reason": "RED_or_no_external_reviewer", "text": "NULL"}
        artifact_path = ""
    elif route["route"] == "deterministic_screen_no_llm":
        result = deterministic_screen_artifact(prompt, route)
        path = SCREEN_DIR / f"{run_id}.screen.json"
        write_json(path, result)
        append_jsonl(LEARNING_BLOCKLIST, {"artifact_path": str(path), "reason": "Aether screen artifact not eligible for Aster training", "created_at": now_iso()})
        artifact_path = str(path)
    else:
        if sentinel is None:
            result = {"status": "reviewer_absent", "text": None}
        else:
            text, model = sentinel.claude_code_referee(prompt, role=route["reviewer"])
            result = {"status": "reviewed" if text else "reviewer_absent", "model": model, "text": text}
        path = PROOF_DIR / f"{run_id}.review.json"
        write_json(path, {"id": run_id, "prompt_sha12": sha12(prompt), "route": route, "result": result, "created_at": now_iso()})
        artifact_path = str(path)

    response_text = json.dumps(result, ensure_ascii=False)
    log_call(
        {
            "id": run_id,
            "created_at": now_iso(),
            "route": route["route"],
            "task_kind": route["task_kind"],
            "risk": route["risk"],
            "reviewer": route.get("reviewer"),
            "learning_allowed": route.get("learning_allowed", False),
            "prompt_sha12": sha12(prompt),
            "response_sha12": sha12(response_text),
            "status": result.get("status") or route["route"],
            "artifact_path": artifact_path,
        }
    )
    return {"id": run_id, "route": route, "result": result, "artifact_path": artifact_path}


def learning_check(path_or_text: str) -> dict[str, Any]:
    marker = path_or_text.strip()
    text = marker
    p = Path(marker)
    if p.exists() and p.is_file():
        text = p.read_text(encoding="utf-8", errors="replace")
    low = text.lower()
    reasons = []
    if "deepseek" in low:
        reasons.append("deepseek_source_forbidden")
    if "deterministic_screen_no_llm" in low or "aether screen" in low:
        reasons.append("screen_artifact_not_training")
    provenance = provenance_registry.check_provenance(text)
    if not provenance.get("clean", True):
        reasons.append("provenance_overlap")
    try:
        obj = json.loads(text)
        if obj.get("learning_allowed") is False:
            reasons.append("artifact_learning_forbidden")
        if str(obj.get("source", "")).lower().startswith("deepseek"):
            reasons.append("deepseek_source_forbidden")
    except Exception:
        pass
    return {
        "allowed_for_aster_learning": not reasons,
        "reasons": sorted(set(reasons)),
        "checked": marker,
        "provenance": provenance,
    }


def status() -> dict[str, Any]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    counts = dict(conn.execute("SELECT route, COUNT(*) FROM calls GROUP BY route").fetchall())
    latest = conn.execute("SELECT id, created_at, route, status, artifact_path FROM calls ORDER BY created_at DESC LIMIT 5").fetchall()
    conn.close()
    return {
        "version": VERSION,
        "db": str(DB_PATH),
        "proof_dir": str(PROOF_DIR),
        "screen_dir": str(SCREEN_DIR),
        "deepseek": "removed",
        "api": "disabled",
        "counts": counts,
        "latest": latest,
    }


def cmd_plan(args: argparse.Namespace) -> int:
    prompt = args.text or Path(args.input).read_text(encoding="utf-8")
    print(json.dumps({"route": choose_route(prompt)}, ensure_ascii=False, indent=2))
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    prompt = args.text or Path(args.input).read_text(encoding="utf-8")
    print(json.dumps(call_route(prompt), ensure_ascii=False, indent=2))
    return 0


def cmd_learning_check(args: argparse.Namespace) -> int:
    report = learning_check(args.path_or_text)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["allowed_for_aster_learning"] else 2


def cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(_: argparse.Namespace) -> int:
    assert choose_route("token = sk-abc12345")["route"] == "local_only"
    screen = choose_route("daily Aether option crypto screen watchlist")
    assert screen["route"] == "deterministic_screen_no_llm"
    assert screen["learning_allowed"] is False
    assert choose_route("should we buy NVDA option")["route"] == "claude_code_opus48"
    assert choose_route("Aster compile Jarvis architecture")["route"] == "claude_code_fable"
    assert learning_check("deepseek_screen_only")["allowed_for_aster_learning"] is False
    assert learning_check("deterministic_screen_no_llm")["allowed_for_aster_learning"] is False
    print("PASS: aether_router_v5 selftest")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aether Router V5")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, func in [("plan", cmd_plan), ("call", cmd_call)]:
        s = sub.add_parser(name)
        s.add_argument("--text")
        s.add_argument("--input")
        s.set_defaults(func=func)
    s = sub.add_parser("learning-check")
    s.add_argument("path_or_text")
    s.set_defaults(func=cmd_learning_check)
    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)
    s = sub.add_parser("selftest")
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd in {"plan", "call"} and not args.text and not args.input:
        raise SystemExit(f"{args.cmd} requires --text or --input")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
