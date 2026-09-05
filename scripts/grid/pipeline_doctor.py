#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline_doctor.py v2 — Grid+CC scan 管线巡检（只读诊断）。

链路: nexus-dryrun pool scan → pool_signals → run_scan(CC) → jsonl → store → aether.html

用法:
  python3 scripts/grid/pipeline_doctor.py
  python3 scripts/grid/pipeline_doctor.py --json
  python3 scripts/grid/pipeline_doctor.py --bark https://api.day.app/YOUR_KEY

原则: 只读不改；每环独立判定；新鲜度第一；查不到标 UNKNOWN。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
HOME = Path.home()
AETHER = REPO / "aether_nexus"
NOW = datetime.now(timezone.utc)
EST = ZoneInfo("America/New_York")
RED, YEL, GRN, UNK = "✗", "▲", "✓", "?"

PATHS = {
    "pool_signals": AETHER / "dryrun_state" / "pool_signals.json",
    "nexus_dryrun_log": HOME / "Library/Logs/demo-aether/nexus-dryrun.err.log",
    "scan_pool": REPO / "data/grid_router/scan_pool.jsonl",
    "scan_offpool": REPO / "data/grid_router/scan_offpool.jsonl",
    "pool_config": AETHER / "pool_config.py",
}

URLS = {
    "gateway": "http://127.0.0.1:8501/health",
    "router": "http://127.0.0.1:8500/health",
    "store_cc": "http://127.0.0.1:8501/store/events/recent?source=aether&kinds=grid_cc_scan&per_kind=3",
}

STALE_HOURS = 20
POOL_TABLE_MIN = 12
FACTOR_WORDS = ["gamma", "iv", "delta", "score", "spread", "点差", "过滤", "passing", "filtered"]


def _factor_blob(text: str) -> str:
    return text.replace("Δ", "delta").replace("δ", "delta").lower()
DEFAULT_BARK = os.environ.get("DOCTOR_BARK_URL", os.environ.get("NOW_BARK_URL", "")).strip()
ENV_FILE = Path(__file__).resolve().parent / "pipeline_doctor.env"


def _configure_ssl() -> None:
    if os.environ.get("SSL_CERT_FILE"):
        return
    for py in (
        AETHER / ".venv" / "bin" / "python",
        Path(sys.executable),
    ):
        if not py.exists() and py != Path(sys.executable):
            continue
        try:
            proc = subprocess.run(
                [str(py), "-m", "certifi"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            ca = (proc.stdout or "").strip()
            if proc.returncode == 0 and ca and Path(ca).is_file():
                os.environ["SSL_CERT_FILE"] = ca
                os.environ["REQUESTS_CA_BUNDLE"] = ca
                return
        except Exception:
            continue


_configure_ssl()

LAUNCH_LABELS = (
    "com.demo.aether.nexus-dryrun",
    "com.grid.poolscan",
    "com.grid.offpoolscan",
)


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_hours(ts: datetime | None, *, note: str = "") -> tuple[float | None, str]:
    if ts is None:
        return None, note or "无时间戳"
    hours = (NOW - ts.astimezone(timezone.utc)).total_seconds() / 3600.0
    return max(0.0, hours), note


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _latest_pool_round() -> dict[str, Any]:
    data = _read_json(PATHS["pool_signals"], [])
    if isinstance(data, list) and data:
        last = data[-1]
        return last if isinstance(last, dict) else {}
    return {}


def _pool_symbol_list() -> list[str]:
    try:
        sys.path.insert(0, str(AETHER))
        from pool_config import pool_symbols  # noqa: WPS433

        return pool_symbols()
    except Exception:
        rnd = _latest_pool_round()
        raw = rnd.get("pool_symbols") or []
        return [str(s).upper() for s in raw if str(s).strip()]


def _pool_rows_from_rejection(rej_path: Path, pool_syms: set[str]) -> dict[str, dict[str, Any]]:
    if not rej_path.is_file():
        return {}
    best: dict[str, dict[str, Any]] = {}
    for ln in rej_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        sym = str(row.get("symbol") or "").upper()
        if sym not in pool_syms:
            continue
        score = row.get("score")
        try:
            score_f = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_f = None
        prev = best.get(sym)
        if prev is not None:
            prev_score = prev.get("score")
            if score_f is not None and prev_score is not None and score_f <= prev_score:
                continue
        best[sym] = {
            "symbol": sym,
            "score": score_f,
            "kill_rule": row.get("kill_rule") or row.get("reason"),
            "status": "filtered",
        }
    return best


def _latest_jsonl(path: Path, *, ok_only: bool = False) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ok_only and not row.get("ok"):
            continue
        return row
    return None


def _log_latest_ts(path: Path) -> datetime | None:
    if not path.is_file():
        return None
    latest: datetime | None = None
    tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
    for line in tail:
        for m in re.findall(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2})?", line):
            dt = _parse_ts(m)
            if dt and (latest is None or dt > latest):
                latest = dt
    if latest is None:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return latest


def check_freshness(name: str, path: Path, ts: datetime | None, *, note: str = "") -> dict[str, Any]:
    if not path.is_file() and ts is None:
        return {"env": name, "status": RED, "detail": f"{path} 不存在"}
    hours, extra = _age_hours(ts, note=note)
    if hours is None:
        return {"env": name, "status": RED, "detail": extra}
    fresh = hours <= STALE_HOURS
    suffix = "" if fresh else f" ← 陈旧!超过 {STALE_HOURS}h"
    return {
        "env": name,
        "status": GRN if fresh else RED,
        "detail": f"{hours:.1f}h 前更新{(' ' + extra) if extra else ''}{suffix}",
    }


def check_launchd(label: str) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in (proc.stdout or "").splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] == label:
                code = parts[1]
                pid = parts[0]
                if pid != "-":
                    return {"env": label, "status": GRN, "detail": f"loaded pid={pid}"}
                if code not in ("0", "-"):
                    return {"env": label, "status": YEL, "detail": f"loaded last_exit={code}"}
                return {"env": label, "status": GRN, "detail": "loaded (idle)"}
        return {"env": label, "status": RED, "detail": "未加载 launchd"}
    except Exception as exc:
        return {"env": label, "status": UNK, "detail": f"launchctl 失败: {exc}"}


def check_pool_signals() -> dict[str, Any]:
    rnd = _latest_pool_round()
    if not rnd:
        return {"env": "② pool_signals", "status": RED, "detail": "无记录"}
    ts = _parse_ts(str(rnd.get("scan_time") or ""))
    row = check_freshness("② pool_signals", PATHS["pool_signals"], ts)
    trade_day = datetime.now(EST).date().isoformat()
    scan_day = ts.astimezone(EST).date().isoformat() if ts else ""
    if scan_day and scan_day != trade_day:
        row["status"] = RED
        row["detail"] += f" ← 不是今天({trade_day})"
    return row


def check_pool_universe_table() -> dict[str, Any]:
    rnd = _latest_pool_round()
    if not rnd:
        return {"env": "pool 全宇宙表", "status": RED, "detail": "pool_signals 空"}
    pool_list = _pool_symbol_list()
    if not pool_list:
        return {"env": "pool 全宇宙表", "status": RED, "detail": "读不到 pool_config 列表"}

    passing = {
        str(r.get("symbol", "")).upper()
        for r in (rnd.get("universe_scores") or rnd.get("candidates") or [])
        if isinstance(r, dict) and r.get("symbol")
    }
    if not rnd.get("universe_scores"):
        n_cand = len(rnd.get("candidates") or [])
        return {
            "env": "pool 全宇宙表",
            "status": RED,
            "detail": f"缺 universe_scores,CC 只见 {n_cand} 只 ← 复读根因",
        }

    rej_path = Path(str(rnd.get("rejection_log") or ""))
    if not rej_path.is_file():
        rej_dir = AETHER / "logs" / "rejections"
        if rej_dir.is_dir():
            files = sorted(rej_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            rej_path = files[0] if files else rej_path
    filtered = _pool_rows_from_rejection(rej_path, set(pool_list)) if rej_path.is_file() else {}

    covered = sum(1 for sym in pool_list if sym in passing or sym in filtered)
    if covered < POOL_TABLE_MIN:
        missing = [s for s in pool_list if s not in passing and s not in filtered]
        return {
            "env": "pool 全宇宙表",
            "status": RED,
            "detail": f"仅 {covered}/{len(pool_list)} 有 quant 行,缺 {missing[:6]}",
        }
    return {
        "env": "pool 全宇宙表",
        "status": GRN,
        "detail": f"{covered}/{len(pool_list)} 有 passing/filtered 行 (passing={len(passing)})",
    }


def check_cc_context_density() -> dict[str, Any]:
    """CC prompt 应含 18 行 universe table,不是 top3 一行."""
    try:
        sys.path.insert(0, str(AETHER))
        from premarket_pool_context import build_pool_premarket_context  # noqa: WPS433

        ctx = build_pool_premarket_context(date.today())
    except Exception as exc:
        return {"env": "CC 输入密度", "status": UNK, "detail": f"无法构建 context: {exc}"}
    lines = [ln for ln in ctx.splitlines() if ln.startswith("- ") and ":" in ln]
    if len(lines) >= POOL_TABLE_MIN:
        return {"env": "CC 输入密度", "status": GRN, "detail": f"universe table {len(lines)} 行"}
    if "Latest pool scan hits:" in ctx and "Full pool universe table" not in ctx:
        return {"env": "CC 输入密度", "status": RED, "detail": "仍是旧版 top3 上下文 ← 复读根因"}
    return {
        "env": "CC 输入密度",
        "status": RED,
        "detail": f"universe table 仅 {len(lines)} 行,不足 {POOL_TABLE_MIN}",
    }


def check_cc_language() -> dict[str, Any]:
    last = _latest_jsonl(PATHS["scan_pool"], ok_only=True)
    if not last:
        last = _latest_jsonl(PATHS["scan_pool"], ok_only=False)
    if not last:
        return {"env": "CC 语言", "status": YEL, "detail": "scan_pool.jsonl 空/不存在"}
    if last.get("ok") is False:
        vf = last.get("verify_failed") or []
        factor_fail = [v for v in vf if str(v).startswith("missing_factor") or str(v).startswith("generic_only")]
        if factor_fail:
            return {"env": "CC 语言", "status": RED, "detail": f"最近 scan 因子校验失败: {factor_fail[:3]}"}
    blob = _factor_blob(json.dumps(last, ensure_ascii=False))
    lines = [ln for ln in (last.get("result") or "").splitlines() if ln.strip().startswith("标的")]
    if lines:
        bad = [i + 1 for i, ln in enumerate(lines) if not any(w in _factor_blob(ln) for w in FACTOR_WORDS[:4])]
        if bad:
            return {"env": "CC 语言", "status": RED, "detail": f"行 {bad} 缺 gamma/iv/delta/score"}
    hits = [w for w in FACTOR_WORDS if w.lower() in blob]
    if hits:
        return {"env": "CC 语言", "status": GRN, "detail": f"最近 ok 输出含因子 {hits[:5]}"}
    return {"env": "CC 语言", "status": RED, "detail": "备注无因子词 ← 泛话/verify 应拒"}


def check_scan_jsonl(name: str, path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"env": name, "status": RED, "detail": f"{path.name} 不存在"}
    last = _latest_jsonl(path, ok_only=False)
    ts = _parse_ts(str((last or {}).get("ts") or ""))
    row = check_freshness(name, path, ts)
    if last and last.get("ok") is False:
        vf = last.get("verify_failed") or last.get("error") or last.get("skip")
        row["status"] = YEL if row["status"] == GRN else row["status"]
        row["detail"] += f" | 末条失败: {vf}"
    elif last and last.get("ok") is True:
        row["detail"] += " | 末条 ok"
    return row


def check_store_grid_cc() -> dict[str, Any]:
    try:
        req = urllib.request.Request(URLS["store_cc"])
        with urllib.request.urlopen(req, timeout=5) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"env": "store grid_cc_scan", "status": RED, "detail": f"不可读: {exc}"}
    if not isinstance(rows, list) or not rows:
        return {"env": "store grid_cc_scan", "status": RED, "detail": "今日无 grid_cc_scan 事件"}
    latest = rows[0]
    payload = latest.get("payload") or {}
    pdate = str(payload.get("date") or "")
    today = datetime.now(EST).date().isoformat()
    if pdate != today:
        return {
            "env": "store grid_cc_scan",
            "status": RED,
            "detail": f"最新 date={pdate or '?'} 不是今天 {today}",
        }
    return {
        "env": "store grid_cc_scan",
        "status": GRN,
        "detail": f"#{latest.get('id')} {payload.get('scan_kind')}/{payload.get('scan_slot')}",
    }


def check_endpoint(name: str, url: str | None) -> dict[str, Any]:
    if not url:
        return {"env": name, "status": UNK, "detail": "未配置(跳过)"}
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            code = resp.status
        return {"env": name, "status": GRN if code == 200 else RED, "detail": f"HTTP {code}"}
    except Exception as exc:
        return {"env": name, "status": RED, "detail": f"不可达: {exc}"}


def _resolve_bark_url(override: str = "") -> str:
    url = (override or DEFAULT_BARK).strip()
    if url:
        return url.rstrip("/")
    if not ENV_FILE.is_file():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        if key.strip() == "DOCTOR_BARK_URL":
            return val.strip().strip('"').strip("'").rstrip("/")
    return ""


def send_bark(title: str, body: str, *, base: str = "") -> str:
    """Return status text; POST first, GET fallback."""
    bark = _resolve_bark_url(base)
    if not bark:
        return "未配置 DOCTOR_BARK_URL"
    payload = json.dumps(
        {"title": title, "body": body, "group": "pipeline-doctor"},
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            bark,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if resp.status == 200 and '"code":200' in raw.replace(" ", ""):
                return "已推送"
            return f"HTTP {resp.status}: {raw[:160]}"
    except Exception as post_err:
        try:
            url = f"{bark}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
            with urllib.request.urlopen(url, timeout=12) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if resp.status == 200:
                    return "已推送(GET)"
                return f"GET HTTP {resp.status}: {raw[:160]}"
        except Exception as get_err:
            return f"失败 POST={post_err} GET={get_err}"


def check_unique_factor_rate_3d() -> dict[str, Any]:
    """近 3 日 unique/总 draft;<0.7 琥珀 <0.5 红。8600 platform.db。"""
    import sqlite3

    db_path = Path(os.environ.get("PLATFORM_DB", str(REPO / "alpha-platform" / "data" / "platform.db")))
    # docker default mount often ./data/platform.db under alpha-platform
    candidates = [
        db_path,
        REPO / "alpha-platform" / "data" / "platform.db",
        REPO / "alpha-platform" / "platform" / "data" / "platform.db",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return {"env": "unique_factor_rate_3d", "status": UNK, "detail": "platform.db 未找到"}
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            cutoff = int(NOW.timestamp()) - 3 * 86400
            rows = c.execute(
                "SELECT code, status FROM factor_drafts WHERE created>=?", (cutoff,)
            ).fetchall()
        finally:
            c.close()
    except Exception as exc:
        return {"env": "unique_factor_rate_3d", "status": UNK, "detail": f"读库失败: {exc}"}
    if not rows:
        return {"env": "unique_factor_rate_3d", "status": UNK, "detail": "近3日无 draft"}
    sys.path.insert(0, str(REPO / "alpha-platform" / "backend"))
    try:
        import factor_dedup  # noqa: WPS433

        # fingerprint without full db helper
        fps = set()
        total = 0
        for code, status in rows:
            total += 1
            if status == "dup_rejected":
                continue
            fps.add(factor_dedup.factor_fingerprint(code or ""))
        unique = len(fps)
        rate = unique / total if total else 1.0
    except Exception as exc:
        return {"env": "unique_factor_rate_3d", "status": UNK, "detail": f"指纹失败: {exc}"}
    if rate < 0.5:
        st = RED
    elif rate < 0.7:
        st = YEL
    else:
        st = GRN
    return {
        "env": "unique_factor_rate_3d",
        "status": st,
        "detail": f"{unique}/{total}={rate:.2f} ({path.name})",
    }


def check_missed_movers() -> dict[str, Any]:
    """movers top-20 ∖ (heat∪watch); >3 琥珀。经 8600 /api/pulse。"""
    url = os.environ.get("ALPHA_PULSE_URL", "http://127.0.0.1:8600/api/pulse")
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            pulse = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"env": "missed_movers", "status": UNK, "detail": f"pulse 不可达: {exc}"}
    heat = set(pulse.get("watchlist") or [])
    gainers = (pulse.get("dailyMovers") or {}).get("gainers") or []
    covered = set(heat)
    missed = []
    for g in gainers[:20]:
        sym = str(g.get("sym") or g.get("symbol") or "").upper()
        if sym and sym not in covered:
            missed.append(f"{sym}:{g.get('ret1d', '?')}%")
    n = len(missed)
    st = YEL if n > 3 else GRN
    sample = ", ".join(missed[:8]) if missed else "无"
    return {
        "env": "missed_movers",
        "status": st,
        "detail": f"n={n} (>3琥珀) · {sample}",
    }


def run() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.append(check_launchd("com.demo.aether.nexus-dryrun"))
    log_ts = _log_latest_ts(PATHS["nexus_dryrun_log"])
    rows.append(check_freshness("① nexus-dryrun log", PATHS["nexus_dryrun_log"], log_ts))
    rows.append(check_pool_signals())
    rows.append(check_pool_universe_table())
    rows.append(check_cc_context_density())
    rows.append(check_scan_jsonl("③ scan_pool 落盘", PATHS["scan_pool"]))
    rows.append(check_cc_language())
    rows.append(check_endpoint("⑤ router 8500", URLS["router"]))
    rows.append(check_endpoint("⑥ gateway 8501", URLS["gateway"]))
    rows.append(check_launchd("com.demo.aether.pool-quant-gate"))
    rows.append(check_unique_factor_rate_3d())
    rows.append(check_missed_movers())
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Grid+CC pipeline doctor (read-only)")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--bark", default="", help="Bark URL prefix; push if any red")
    ap.add_argument("--test-bark", action="store_true", help="send one test Bark and exit")
    args = ap.parse_args()
    bark = (args.bark or _resolve_bark_url()).strip()

    if args.test_bark:
        status = send_bark("管线告警·测试", "pipeline_doctor Bark 通路 OK", base=bark)
        print(status)
        raise SystemExit(0 if status.startswith("已推送") else 1)

    rows = run()
    reds = [r for r in rows if r["status"] == RED]

    if args.json:
        print(
            json.dumps(
                {
                    "ts": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "repo": str(REPO),
                    "reds": len(reds),
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        local = NOW.astimezone()
        print(f"\n=== 管线巡检 {local.strftime('%m-%d %H:%M %Z')} ===")
        print(f" repo: {REPO}")
        for row in rows:
            print(f" {row['status']}  {row['env']:<22} {row['detail']}")
        print("─" * 56)
        if reds:
            print(f" {len(reds)} 处红项 — 从上游往下修:")
            for row in reds:
                print(f"   → {row['env']}: {row['detail']}")
        else:
            print(" 全链新鲜,无红项。")

    if bark and reds:
        body = "管线 %d 红: %s" % (len(reds), " / ".join(r["env"] for r in reds))
        bark_status = send_bark("管线告警", body, base=bark)
        if not args.json:
            print(f" Bark → {bark_status}")

    raise SystemExit(1 if reds else 0)


if __name__ == "__main__":
    main()
