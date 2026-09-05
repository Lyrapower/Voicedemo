#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_scan.py v2 — 定时经 router 调 CC 跑扫描(pool / offpool)。

用法:
    python3 run_scan.py pool
    python3 run_scan.py offpool

v2(2026-07-20) — 审查九条(R1–R9); 本仓库叠加 aether 动态上下文(pool/offpool)。

环境变量:
    SCAN_ROUTER / GRID_ROUTER_URL  (默认 http://127.0.0.1:8500)
    SCAN_OUT_DIR / ROUTER_DIR      (默认 <repo>/data/grid_router)
    SCAN_DAILY_MAX                 (默认 4)
    SCAN_TIMEOUT                   (默认 1200 秒)
纯 stdlib + aether_nexus 动态 prompt 段。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AETHER = ROOT / "aether_nexus"
sys.path.insert(0, str(AETHER))

KIND = sys.argv[1] if len(sys.argv) > 1 else "pool"
SCAN_SLOT = os.environ.get("SCAN_SLOT", "").strip().lower()
ROUTER = os.environ.get(
    "SCAN_ROUTER",
    os.environ.get("GRID_ROUTER_URL", "http://127.0.0.1:8500")
    .replace("/v1/chat/completions", "")
    .rstrip("/"),
)
DEFAULT_OUT = ROOT / "data" / "grid_router"
OUT_DIR = Path(
    os.environ.get("SCAN_OUT_DIR")
    or os.environ.get("ROUTER_DIR")
    or str(DEFAULT_OUT)
).expanduser()
DAILY_MAX = int(os.environ.get("SCAN_DAILY_MAX", "4"))
SCAN_BUDGET_FILES = ("scan_pool.jsonl", "scan_offpool.jsonl")
AUDIT_KEYS = ("cost_usd", "duration_ms", "resolved_models")
TIMEOUT = int(os.environ.get("SCAN_TIMEOUT", "1200"))

PROMPT_FILE = Path(__file__).parent / ("prompt_%s.md" % KIND)
OUT = OUT_DIR / ("scan_%s.jsonl" % KIND)
LOCK = OUT_DIR / ("scan_%s.lock" % KIND)

EXPECTED_MARKS = ["标的："] if KIND == "pool" else ['"items"']
# Pool factor marks — verified per 标的 line via verify_pool_factor_lines()
FACTOR_MARKS = ["gamma", "iv", "delta", "score"]
REQUIRED_FACTOR_WORDS = FACTOR_MARKS
GENERIC_BANNED_PHRASES = (
    "技术面强劲",
    "基本面良好",
    "趋势向上",
    "动能充足",
    "蓄势待发",
    "宏观利好",
    "题材活跃",
    "资金关注",
    "强势格局",
    "看好后市",
)
MIN_RESULT_CHARS = 200

US_MARKET_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(entry: dict) -> None:
    entry.setdefault("ts", utcnow())
    entry.setdefault("kind", KIND)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(json.dumps(entry, ensure_ascii=False)[:200])


def bail(stage: str, error: object) -> None:
    emit({"ok": False, "stage": stage, "error": str(error)[:500]})
    sys.exit(1)


def _dynamic_context(kind: str) -> str:
    if kind == "pool":
        from premarket_pool_context import build_pool_premarket_context

        return build_pool_premarket_context(date.today())
    if kind == "offpool":
        from offpool_scan_context import build_offpool_context

        return build_offpool_context(date.today())
    return ""


def _ensure_fresh_pool_signals() -> None:
    """Refresh pool_signals via aether_dryrun when stale — CC must not read old top3."""
    script = Path(__file__).parent / "ensure_pool_scan.py"
    venv_py = ROOT / "aether_nexus" / ".venv" / "bin" / "python"
    py = venv_py if venv_py.is_file() else Path(sys.executable)
    try:
        subprocess.run(
            [str(py), str(script)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except Exception:
        pass


def infer_scan_slot() -> str:
    if SCAN_SLOT:
        return SCAN_SLOT
    now = datetime.now().astimezone()
    hm = now.hour * 60 + now.minute
    if hm <= 8 * 60:
        return "premarket"
    if hm <= 12 * 60 + 30:
        return "intraday"
    return "postmarket"


def _pool_candidate_lines(result: str) -> list[str]:
    lines: list[str] = []
    for raw in (result or "").splitlines():
        line = raw.strip()
        if line.startswith("标的：") or line.startswith("标的:"):
            lines.append(line)
    return lines


def verify_pool_factor_lines(result: str) -> list[str]:
    """Each 标的 line must cite gamma/iv/delta/score; generic fluff fails."""
    failed: list[str] = []
    lines = _pool_candidate_lines(result)
    if not lines:
        failed.append("missing_mark:标的：")
        return failed
    for idx, line in enumerate(lines, 1):
        low = line.lower()
        has_factor = any(word in low for word in REQUIRED_FACTOR_WORDS)
        if not has_factor:
            failed.append("missing_factor:%s(line%d)" % ("/".join(REQUIRED_FACTOR_WORDS), idx))
        if any(phrase in line for phrase in GENERIC_BANNED_PHRASES) and not has_factor:
            failed.append("generic_only:line%d" % idx)
    return failed


def gate_market_day() -> None:
    now = datetime.now().astimezone()
    if now.weekday() >= 5:
        emit({"ok": False, "stage": "gate", "skip": "weekend"})
        sys.exit(0)
    if now.strftime("%Y-%m-%d") in US_MARKET_HOLIDAYS_2026:
        emit({"ok": False, "stage": "gate", "skip": "market_holiday"})
        sys.exit(0)


def gate_lock() -> None:
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text().strip())
            os.kill(pid, 0)
            emit({"ok": False, "stage": "gate", "skip": "overlap(pid %d still running)" % pid})
            sys.exit(0)
        except (ValueError, ProcessLookupError, PermissionError):
            LOCK.unlink(missing_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()))


def _entry_local_date(entry: dict) -> str:
    ets = entry.get("ts", "")
    try:
        d = datetime.strptime(ets, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return d.astimezone().strftime("%Y-%m-%d")
    except Exception:
        return ""


def _today_cc_calls() -> int:
    """Shared pool+offpool budget — all non-gate jsonl lines count."""
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    calls = 0
    for name in SCAN_BUDGET_FILES:
        path = OUT_DIR / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").strip().splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("stage") == "gate":
                continue
            # 失败/未登录不占预算,避免 cc_not_logged_in 连烧 4 次锁死当日
            if e.get("ok") is False:
                continue
            if _entry_local_date(e) == today:
                calls += 1
    return calls


def gate_daily_budget() -> None:
    calls = _today_cc_calls()
    if calls >= DAILY_MAX:
        emit(
            {
                "ok": False,
                "stage": "gate",
                "skip": "daily_budget(%d/%d shared pool+offpool)" % (calls, DAILY_MAX),
            }
        )
        sys.exit(0)


def audit_from_grid_meta(resp: dict) -> dict:
    gm = resp.get("grid_meta") or {}
    audit: dict = {}
    for key in AUDIT_KEYS:
        val = gm.get(key)
        if val is not None:
            audit[key] = val
    return audit


def _kickstart_router() -> None:
    """Grid+CC 依赖 :8500；launchd 标签 com.grid.router。"""
    label = "gui/%d/com.grid.router" % os.getuid()
    try:
        subprocess.run(
            ["launchctl", "kickstart", "-k", label],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception:
        pass
    time.sleep(2)


def _router_health_ok() -> tuple[bool, str]:
    try:
        req = urllib.request.Request(ROUTER.rstrip("/") + "/health")
        resp = urllib.request.urlopen(req, timeout=8)
        server = resp.headers.get("Server", "")
        if "GridRouter" not in server:
            return False, "端口在线但 Server=%r,不是 GridRouter" % server
        health = json.loads(resp.read().decode("utf-8"))
        cloud = str(health.get("cloud", ""))
        if not cloud.startswith("cli:"):
            return False, "router 在线但 cloud 目标不可用: %s" % cloud
        return True, ""
    except urllib.error.URLError as e:
        return False, "router %s 不可达: %s" % (ROUTER, e)


def gate_router() -> None:
    ok, err = _router_health_ok()
    if ok:
        return
    _kickstart_router()
    ok, err2 = _router_health_ok()
    if ok:
        return
    bail("router_verify", err2 or err)


def gate_cc_login() -> None:
    """CC CLI 未登录时直接 gate,避免反复 HTTP 502 exit_1 污染 jsonl。"""
    cli = ""
    try:
        req = urllib.request.Request(ROUTER.rstrip("/") + "/health")
        resp = urllib.request.urlopen(req, timeout=8)
        body = json.loads(resp.read().decode("utf-8"))
        cloud = str(body.get("cloud") or "")
        if cloud.startswith("cli:"):
            cli = cloud[4:]
    except Exception:
        return
    if not cli or not Path(cli).exists():
        return
    try:
        proc = subprocess.run(
            [cli, "-p", "--output-format", "json", "--model",
             os.environ.get("GRID_SCAN_CLI_MODEL", "claude-sonnet-4-6")],
            input=b"reply:ok",
            capture_output=True,
            timeout=45,
        )
    except Exception as e:  # noqa: BLE001
        bail("cc_login", "claude 探针失败: %s" % e)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err_txt = (proc.stderr or b"").decode("utf-8", "replace")
    blob = (out + "\n" + err_txt).lower()
    if "not logged in" in blob or "/login" in blob:
        bail(
            "cc_login",
            "Claude Code 未登录 — 在本机终端执行: %s 然后 /login(或 claude login)"
            % cli,
        )
    if proc.returncode != 0:
        # 其它硬失败也提前暴露(含 auth)
        detail = out.strip()[:240] or err_txt.strip()[:240] or ("exit_%d" % proc.returncode)
        try:
            env = json.loads(out)
            if isinstance(env, dict) and env.get("result"):
                detail = str(env.get("result"))[:240]
        except Exception:
            pass
        if "not logged in" in detail.lower() or "/login" in detail.lower():
            bail("cc_login", "Claude Code 未登录 — %s" % detail)
        # 非登录类失败留给主请求(避免误杀瞬态)


def emit_store(entry: dict) -> None:
    """Fail-open: surface Grid+CC scan in aether.html via /store/events."""
    if not entry.get("ok"):
        return
    manifest = entry.get("manifest") or {}
    stats = {k: manifest[k] for k in AUDIT_KEYS if manifest.get(k) is not None}
    payload = {
        "date": date.today().isoformat(),
        "lane": "grid_cc",
        "scan_kind": KIND,
        "scan_slot": manifest.get("scan_slot") or infer_scan_slot(),
        "ok": True,
        "result": (entry.get("result") or "")[:4000],
        "manifest": manifest,
        "ts": entry.get("ts") or utcnow(),
    }
    if stats:
        payload["stats"] = stats
    body = json.dumps(
        {"source": "aether", "kind": "grid_cc_scan", "payload": payload},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8501/store/events",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def main() -> None:
    if KIND == "offpool" and os.getenv("OFFPOOL_SCAN_VIA_DAEMON", "1") not in ("0", "false", "False"):
        emit(
            {
                "ok": False,
                "stage": "gate",
                "skip": "offpool via com.demo.aether.offpool (Sonnet+DeepSeek dual-lane)",
            }
        )
        sys.exit(0)
    gate_market_day()
    gate_lock()
    try:
        gate_daily_budget()
        gate_router()
        gate_cc_login()

        if not PROMPT_FILE.exists():
            bail("manifest", "prompt 文件不在 %s" % PROMPT_FILE)

        if KIND == "pool":
            _ensure_fresh_pool_signals()

        static = PROMPT_FILE.read_text(encoding="utf-8").strip()
        dynamic = _dynamic_context(KIND)
        prompt_text = (dynamic + "\n\n" + static).strip() if dynamic else static
        blob = prompt_text.encode("utf-8")

        manifest = {
            "prompt_file": str(PROMPT_FILE),
            "prompt_sha256": hashlib.sha256(blob).hexdigest()[:16],
            "prompt_bytes": len(blob),
            "dynamic_context": bool(dynamic),
            "router": ROUTER,
            "scan_slot": infer_scan_slot(),
            "data_source": "pool_signals+fresh_scan" if KIND == "pool" else "prompt_only",
            "data_caveat": "pool_universe_table" if KIND == "pool" else "UNVERIFIED_NO_MARKET_DATA",
        }

        payload = {
            "model": "",
            "confirmed": True,
            "messages": [{"role": "user", "content": "/scan " + prompt_text}],
            "stream": False,
        }
        req = urllib.request.Request(
            ROUTER.rstrip("/") + "/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            bail("http", "HTTP %d: %s" % (e.code, e.read()[:300]))
        except Exception as e:  # noqa: BLE001
            bail("http", e)

        finish = ""
        try:
            finish = str(resp["choices"][0].get("finish_reason") or "")
        except (KeyError, IndexError, TypeError):
            pass
        if finish in ("cc_cli_error", "cc_candidate"):
            bail("router", "unexpected finish_reason=%s" % finish)
        if resp.get("error"):
            bail("router", json.dumps(resp.get("error"))[:300])

        audit = audit_from_grid_meta(resp)

        try:
            result = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            bail("schema", "CC 返回不符合预期结构: %s | raw=%s" % (e, json.dumps(resp)[:300]))

        verify_failed: list[str] = []
        if not result or len(result) < MIN_RESULT_CHARS:
            verify_failed.append(
                "too_short(%d<%d)" % (len(result or ""), MIN_RESULT_CHARS)
            )
        for mark in EXPECTED_MARKS:
            if mark not in result:
                verify_failed.append("missing_mark:%s" % mark)
        if KIND == "pool":
            verify_failed.extend(verify_pool_factor_lines(result))

        manifest.update(audit)
        entry = {
            "ok": not verify_failed,
            "manifest": manifest,
            "result": result,
        }
        entry.update(audit)
        if verify_failed:
            entry["verify_failed"] = verify_failed
        emit(entry)
        emit_store(entry)
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
