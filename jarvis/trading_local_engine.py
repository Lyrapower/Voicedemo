from __future__ import annotations

import csv
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

CONFIG_PATH = ROOT / "config" / "trading.yaml"
UPLOADS_DIR = ROOT / "data" / "trading" / "uploads"
PROCESSED_DIR = ROOT / "data" / "trading" / "processed"
REJECTED_DIR = ROOT / "data" / "trading" / "rejected"
EVENTS_DIR = ROOT / "data" / "trading" / "events"
PROOF_DIR = ROOT / "deliver" / "proof" / "trading"

FAST_GATE_REPORT_PATH = PROOF_DIR / "FAST_GATE_REPORT.md"
DAILY_READINESS_REPORT_PATH = PROOF_DIR / "DAILY_READINESS_REPORT.md"
ACCEPTANCE_REPORT_PATH = PROOF_DIR / "ACCEPTANCE_REPORT.md"

REQUIRED_UPLOAD_COLUMNS = [
    "ticker",
    "timestamp",
    "price",
    "vwap",
    "open_range_high",
    "volume",
    "avg_volume",
    "iv_rank",
    "entry_low",
    "entry_high",
    "sell_low",
    "sell_high",
    "stop",
]

DEFAULT_CONFIG: dict[str, Any] = {
    "external_signals_enabled": False,
    "tradingview_webhook_enabled": False,
    "tradingview_shared_secret_env": "JARVIS_TV_WEBHOOK_SECRET",
    "public_webhook_url": "",
    "core_pool": ["MU", "AMD", "IREN"],
    "excluded": ["TSLA"],
    "replacement_watchlist": ["NBIS", "PR", "APLD", "LITE"],
    "build_radar": ["STM", "ON"],
    "rvol_min": 1.5,
    "iv_rank_max": 75,
    "max_trades_per_week": 3,
    "upload_retention_hours": 72,
    "manual_execution_only": True,
    "broker_execution": False,
}


@dataclass
class LocalUploadResult:
    status: str
    processed_files: list[str]
    rejected_files: list[str]
    deleted_files: list[str]
    rows_count: int
    latest_snapshot: dict[str, Any] | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dirs() -> None:
    for path in (UPLOADS_DIR, PROCESSED_DIR, REJECTED_DIR, EVENTS_DIR, PROOF_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    if v in {"true", "True"}:
        return True
    if v in {"false", "False"}:
        return False
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    return v


def _parse_yaml_stdlib(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        line = raw.rstrip()
        if line.lstrip().startswith("- "):
            if current_list_key:
                item = line.split("-", 1)[1].strip()
                data.setdefault(current_list_key, []).append(_parse_scalar(item))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = []
            current_list_key = key
        else:
            data[key] = _parse_scalar(value)
            current_list_key = None
    return data


def load_trading_config() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if not CONFIG_PATH.exists():
        return config

    parsed: dict[str, Any] = {}
    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            parsed = payload
    except Exception:
        parsed = _parse_yaml_stdlib(CONFIG_PATH)

    for key, default in DEFAULT_CONFIG.items():
        value = parsed.get(key, default)
        if isinstance(default, list):
            if isinstance(value, list):
                config[key] = [str(x).upper() for x in value]
            else:
                config[key] = list(default)
            continue
        if isinstance(default, bool):
            config[key] = bool(value)
            continue
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                config[key] = int(value)
            except Exception:
                config[key] = default
            continue
        if isinstance(default, float):
            try:
                config[key] = float(value)
            except Exception:
                config[key] = default
            continue
        config[key] = str(value)
    return config


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _parse_rows_from_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        missing = [col for col in REQUIRED_UPLOAD_COLUMNS if col not in reader.fieldnames]
        if missing:
            raise ValueError("CSV missing required columns: " + ",".join(missing))
        for row in reader:
            rows.append({k: row.get(k, "") for k in REQUIRED_UPLOAD_COLUMNS})
    return rows


def _parse_rows_from_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    if isinstance(payload, dict):
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("JSON payload must be object or list")
    normalized: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"JSON row {idx} is not object")
        missing = [col for col in REQUIRED_UPLOAD_COLUMNS if col not in row]
        if missing:
            raise ValueError("JSON missing required columns: " + ",".join(missing))
        normalized.append({k: row.get(k, "") for k in REQUIRED_UPLOAD_COLUMNS})
    return normalized


def _delete_old_uploads(retention_hours: int) -> list[str]:
    cutoff = _now() - timedelta(hours=retention_hours)
    deleted: list[str] = []
    for path in sorted(UPLOADS_DIR.glob("*")):
        if not path.is_file():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if modified < cutoff:
            deleted.append(str(path.relative_to(ROOT)))
            path.unlink(missing_ok=True)
    return deleted


def run_local_upload_engine() -> LocalUploadResult:
    _ensure_dirs()
    cfg = load_trading_config()
    deleted_files = _delete_old_uploads(int(cfg.get("upload_retention_hours", 72)))

    processed_files: list[str] = []
    rejected_files: list[str] = []
    rows_all: list[dict[str, Any]] = []

    for path in sorted(UPLOADS_DIR.glob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        try:
            if ext == ".csv":
                rows = _parse_rows_from_csv(path)
            elif ext == ".json":
                rows = _parse_rows_from_json(path)
            else:
                raise ValueError("unsupported file extension")
            rows_all.extend(rows)
            dest = PROCESSED_DIR / path.name
            if dest.exists():
                dest = PROCESSED_DIR / f"{path.stem}_{int(_now().timestamp())}{path.suffix}"
            shutil.move(str(path), str(dest))
            processed_files.append(str(dest.relative_to(ROOT)))
        except Exception:
            dest = REJECTED_DIR / path.name
            if dest.exists():
                dest = REJECTED_DIR / f"{path.stem}_{int(_now().timestamp())}{path.suffix}"
            shutil.move(str(path), str(dest))
            rejected_files.append(str(dest.relative_to(ROOT)))

    latest_snapshot = None
    if rows_all:
        latest_snapshot = {
            "generated_at": _now_iso(),
            "rows_count": len(rows_all),
            "tickers": sorted({str(r.get("ticker", "")).upper() for r in rows_all if r.get("ticker")}),
            "source": "local_uploads_only",
            "purpose": "premarket prep, post-trade review, build radar, proof archive",
            "not_primary_opening_window_path": True,
        }
        snapshot_name = f"market_snapshot_{_now().strftime('%Y%m%dT%H%M%SZ')}.json"
        (PROCESSED_DIR / snapshot_name).write_text(
            json.dumps({"rows": rows_all, "meta": latest_snapshot}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    status = "NO_LOCAL_DATA" if not rows_all else "READY"
    return LocalUploadResult(
        status=status,
        processed_files=processed_files,
        rejected_files=rejected_files,
        deleted_files=deleted_files,
        rows_count=len(rows_all),
        latest_snapshot=latest_snapshot,
    )


def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    if "secret" in redacted:
        redacted["secret"] = "REDACTED"
    return redacted


def _latest_event_log_path() -> Path | None:
    files = sorted(EVENTS_DIR.glob("*_tradingview_events.jsonl"))
    return files[-1] if files else None


def latest_event_age_minutes() -> int | None:
    latest = _latest_event_log_path()
    if not latest or not latest.exists():
        return None
    latest_time: datetime | None = None
    for line in latest.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            payload = json.loads(line)
            ts = payload.get("received_at")
            if not isinstance(ts, str):
                continue
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if latest_time is None or dt > latest_time:
                latest_time = dt
        except Exception:
            continue
    if latest_time is None:
        return None
    return int((_now() - latest_time).total_seconds() // 60)


def _append_event(payload: dict[str, Any], result: dict[str, Any]) -> str:
    _ensure_dirs()
    event_path = EVENTS_DIR / f"{_now().strftime('%Y-%m-%d')}_tradingview_events.jsonl"
    event = {
        "received_at": _now_iso(),
        "ticker": str(payload.get("ticker", "")).upper(),
        "source": str(payload.get("source", "")),
        "payload": _redact_payload(payload),
        "verdict": result.get("verdict"),
        "failed_checks": result.get("failed_checks", []),
        "reason": result.get("reason", ""),
        "refused": bool(result.get("verdict") == "AUTH_FAILED"),
    }
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return str(event_path.relative_to(ROOT))


def _write_fast_gate_report(payload: dict[str, Any], result: dict[str, Any], event_log_path: str) -> None:
    lines = [
        "# Trading Fast Gate Report",
        "",
        f"Generated: {_now_iso()}",
        "",
        "## Input",
        f"- Source: {payload.get('source', 'unknown')}",
        f"- Ticker: {str(payload.get('ticker', '')).upper()}",
        f"- Timestamp: {payload.get('timestamp', 'missing')}",
        f"- Price: {payload.get('price', 'missing')}",
        f"- VWAP: {payload.get('vwap', 'missing')}",
        f"- Open Range High: {payload.get('open_range_high', 'missing')}",
        f"- RVOL: {payload.get('rvol', 'missing')}",
        f"- IV Rank: {payload.get('iv_rank', 'missing')}",
        "",
        "## Gate Result",
        f"- Verdict: {result.get('verdict')}",
        f"- Reason: {result.get('reason')}",
        f"- Failed checks: {', '.join(result.get('failed_checks', [])) or 'NONE'}",
        f"- Event log path: {event_log_path}",
        "- Manual execution only: true",
        "- Broker execution: false",
        "- Never outputs BUY: true",
    ]
    FAST_GATE_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _is_tunnel_mode(config: dict[str, Any]) -> bool:
    config_url = str(config.get("public_webhook_url") or "").strip()
    env_url = str(os.environ.get("PUBLIC_WEBHOOK_URL", "")).strip()
    return bool(config_url or env_url)


def _required_webhook_secret() -> str:
    return str(os.environ.get("TRADINGVIEW_WEBHOOK_SECRET", "")).strip()


def evaluate_tradingview_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure_dirs()
    cfg = load_trading_config()

    required = [
        "source",
        "ticker",
        "timestamp",
        "price",
        "vwap",
        "open_range_high",
        "rvol",
        "signal",
    ]
    missing = [key for key in required if payload.get(key) in (None, "")]
    if missing:
        result = {
            "verdict": "INVALID_PAYLOAD",
            "reason": "Missing required fields",
            "failed_checks": ["MISSING_FIELDS:" + ",".join(missing)],
        }
        event_log_path = _append_event(payload, result)
        _write_fast_gate_report(payload, result, event_log_path)
        return result

    if not cfg.get("external_signals_enabled") or not cfg.get("tradingview_webhook_enabled"):
        result = {
            "verdict": "CONFIG_DISABLED",
            "reason": "TradingView webhooks disabled in config",
            "failed_checks": ["CONFIG_DISABLED"],
        }
        event_log_path = _append_event(payload, result)
        _write_fast_gate_report(payload, result, event_log_path)
        return result

    expected_secret = _required_webhook_secret()
    payload_secret = str(payload.get("secret") or "").strip()
    tunnel_mode = _is_tunnel_mode(cfg)
    if tunnel_mode and not expected_secret:
        result = {
            "verdict": "AUTH_FAILED",
            "reason": "Refused: TRADINGVIEW_WEBHOOK_SECRET is required when tunnel/public URL is enabled",
            "failed_checks": ["SECRET_REQUIRED_FOR_TUNNEL"],
        }
        event_log_path = _append_event(payload, result)
        _write_fast_gate_report(payload, result, event_log_path)
        return result
    if expected_secret:
        if not payload_secret:
            result = {
                "verdict": "AUTH_FAILED",
                "reason": "Refused: webhook secret missing in payload",
                "failed_checks": ["SECRET_MISSING"],
            }
            event_log_path = _append_event(payload, result)
            _write_fast_gate_report(payload, result, event_log_path)
            return result
        if payload_secret != expected_secret:
            result = {
                "verdict": "AUTH_FAILED",
                "reason": "Refused: webhook secret mismatch",
                "failed_checks": ["SECRET_MISMATCH"],
            }
            event_log_path = _append_event(payload, result)
            _write_fast_gate_report(payload, result, event_log_path)
            return result

    ticker = str(payload.get("ticker", "")).upper()
    price = _safe_float(payload.get("price"))
    vwap = _safe_float(payload.get("vwap"))
    open_range_high = _safe_float(payload.get("open_range_high"))
    rvol = _safe_float(payload.get("rvol"))
    iv_rank = _safe_float(payload.get("iv_rank"))

    if None in (price, vwap, open_range_high, rvol):
        result = {
            "verdict": "INVALID_PAYLOAD",
            "reason": "Invalid numeric fields",
            "failed_checks": ["INVALID_NUMERIC_FIELDS"],
        }
        event_log_path = _append_event(payload, result)
        _write_fast_gate_report(payload, result, event_log_path)
        return result

    if ticker in {t.upper() for t in cfg.get("excluded", [])}:
        result = {
            "verdict": "BLOCKED",
            "reason": "Ticker excluded by discipline policy",
            "failed_checks": ["TICKER_EXCLUDED"],
        }
        event_log_path = _append_event(payload, result)
        _write_fast_gate_report(payload, result, event_log_path)
        return result

    core_pool = {t.upper() for t in cfg.get("core_pool", [])}
    if ticker not in core_pool:
        result = {
            "verdict": "WATCH",
            "reason": "Ticker outside core opening-window pool",
            "failed_checks": ["OUTSIDE_CORE_POOL"],
        }
        event_log_path = _append_event(payload, result)
        _write_fast_gate_report(payload, result, event_log_path)
        return result

    if iv_rank is None:
        result = {
            "verdict": "CASH",
            "reason": "IV rank missing from payload",
            "failed_checks": ["IV_UNKNOWN"],
        }
        event_log_path = _append_event(payload, result)
        _write_fast_gate_report(payload, result, event_log_path)
        return result

    failed_checks: list[str] = []
    if not (price > vwap):
        failed_checks.append("PRICE_ABOVE_VWAP")
    if not (price > open_range_high):
        failed_checks.append("PRICE_ABOVE_OPEN_RANGE_HIGH")
    if not (rvol >= float(cfg.get("rvol_min", 1.5))):
        failed_checks.append("RVOL_MIN")
    if not (iv_rank <= float(cfg.get("iv_rank_max", 75))):
        failed_checks.append("IV_RANK_MAX")

    if failed_checks:
        result = {
            "verdict": "CASH",
            "reason": "Core pool ticker failed opening-window checks",
            "failed_checks": failed_checks,
        }
    else:
        result = {
            "verdict": "READY_MANUAL_ONLY",
            "reason": "All opening-window checks passed",
            "failed_checks": [],
        }

    event_log_path = _append_event(payload, result)
    _write_fast_gate_report(payload, result, event_log_path)
    return result


def run_daily_readiness_check() -> dict[str, Any]:
    _ensure_dirs()
    cfg = load_trading_config()
    checks: list[dict[str, str]] = []
    unknowns: list[str] = []
    actions: list[str] = []

    def add_check(label: str, ok: bool, detail: str = "") -> None:
        checks.append({"label": label, "status": "PASS" if ok else "FAIL", "detail": detail})

    add_check("config/trading.yaml exists", CONFIG_PATH.exists())
    add_check(
        "core pool is MU/AMD/IREN",
        [x.upper() for x in cfg.get("core_pool", [])] == ["MU", "AMD", "IREN"],
        ",".join(cfg.get("core_pool", [])),
    )
    add_check("TSLA excluded", "TSLA" in [x.upper() for x in cfg.get("excluded", [])])

    webhook_enabled = bool(cfg.get("tradingview_webhook_enabled"))
    external_enabled = bool(cfg.get("external_signals_enabled"))
    add_check("tradingview_webhook_enabled state", True, str(webhook_enabled).lower())
    add_check("external_signals_enabled state", True, str(external_enabled).lower())

    secret_present = bool(_required_webhook_secret())
    tunnel_mode = _is_tunnel_mode(cfg)
    secret_ok = (not webhook_enabled) or (not tunnel_mode) or secret_present
    add_check("TRADINGVIEW_WEBHOOK_SECRET present when tunnel/public URL is enabled", secret_ok)
    if webhook_enabled and tunnel_mode and not secret_present:
        actions.append("Set env var TRADINGVIEW_WEBHOOK_SECRET before enabling public webhook ingress.")

    public_url = str(cfg.get("public_webhook_url") or "").strip()
    public_url_ok = (not webhook_enabled) or bool(public_url)
    add_check("public_webhook_url set when webhook enabled", public_url_ok, public_url or "MISSING")
    if webhook_enabled and not public_url:
        actions.append("Set public_webhook_url to your public HTTPS endpoint.")

    add_check("data/trading/events exists", EVENTS_DIR.exists())
    add_check("deliver/proof/trading exists", PROOF_DIR.exists())
    add_check("docs/TRADINGVIEW_ALERT_SETUP.md exists", (ROOT / "docs" / "TRADINGVIEW_ALERT_SETUP.md").exists())
    add_check("docs/TRADINGVIEW_PINE_ALERT.md exists", (ROOT / "docs" / "TRADINGVIEW_PINE_ALERT.md").exists())
    add_check(
        "tradingview/jarvis_orh_vwap_rvol_gate.pine exists",
        (ROOT / "tradingview" / "jarvis_orh_vwap_rvol_gate.pine").exists(),
    )
    add_check("scripts/test_tradingview_webhook.sh exists", (ROOT / "scripts" / "test_tradingview_webhook.sh").exists())

    age = latest_event_age_minutes()
    if age is None:
        unknowns.append("Latest webhook event age: UNKNOWN (no event yet)")
        unknowns.append(
            "TradingView alerts cannot be verified from Jarvis unless a recent event exists; action: send test webhook"
        )
        actions.append("Send a test webhook using bash scripts/test_tradingview_webhook.sh")
    else:
        checks.append({"label": "latest webhook event age", "status": "PASS", "detail": f"{age} minutes"})

    fast_gate_exists = FAST_GATE_REPORT_PATH.exists()
    checks.append(
        {
            "label": "latest FAST_GATE_REPORT.md",
            "status": "PASS" if fast_gate_exists else "FAIL",
            "detail": str(FAST_GATE_REPORT_PATH.relative_to(ROOT)) if fast_gate_exists else "missing",
        }
    )

    ready = (
        all(c["status"] == "PASS" for c in checks)
        and webhook_enabled
        and external_enabled
        and ((not tunnel_mode) or secret_present)
        and bool(public_url)
    )
    verdict = "READY" if ready else "NOT_READY"

    lines = [
        "# Trading Daily Readiness Report",
        "",
        f"Generated: {_now_iso()}",
        f"Verdict: {verdict}",
        "",
        "## Checks",
    ]
    for c in checks:
        detail = f" ({c['detail']})" if c.get("detail") else ""
        lines.append(f"- {c['status']} - {c['label']}{detail}")
    lines.extend(["", "## Unknowns"])
    if unknowns:
        lines.extend([f"- {u}" for u in unknowns])
    else:
        lines.append("- NONE")
    lines.extend(["", "## Required User Action"])
    if actions:
        lines.extend([f"- {a}" for a in dict.fromkeys(actions)])
    else:
        lines.append("- NONE")
    lines.extend(
        [
            "",
            "- TradingView does not need to stay open after alerts are created",
            "- Jarvis receiver must stay online",
            "- 127.0.0.1 cannot receive TradingView cloud webhooks",
            "",
            f"FINAL VERDICT: {verdict}",
        ]
    )
    DAILY_READINESS_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "generated_at": _now_iso(),
        "verdict": verdict,
        "checks": checks,
        "unknowns": unknowns,
        "required_action": list(dict.fromkeys(actions)) or ["NONE"],
        "latest_webhook_event_age_minutes": age,
        "webhook_enabled": webhook_enabled,
        "external_enabled": external_enabled,
        "secret_present": secret_present,
        "public_webhook_url_set": bool(public_url),
        "proof_path": str(DAILY_READINESS_REPORT_PATH.relative_to(ROOT)),
    }


def get_trading_ui_snapshot() -> dict[str, Any]:
    _ensure_dirs()
    cfg = load_trading_config()
    upload_result = run_local_upload_engine()
    event_path = _latest_event_log_path()
    latest_event = None
    if event_path:
        lines = event_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if lines:
            try:
                latest_event = json.loads(lines[-1])
            except Exception:
                latest_event = None
    readiness = run_daily_readiness_check()
    return {
        "config": cfg,
        "upload_result": upload_result,
        "latest_event": latest_event,
        "latest_event_age_minutes": latest_event_age_minutes(),
        "event_log_path": str(event_path.relative_to(ROOT)) if event_path else "data/trading/events/*_tradingview_events.jsonl",
        "proof_path": str(FAST_GATE_REPORT_PATH.relative_to(ROOT)),
        "readiness": readiness,
    }


def write_acceptance_report(checks: list[tuple[str, bool, str]]) -> str:
    _ensure_dirs()
    verdict = "PASS" if all(ok for _, ok, _ in checks) else "FAIL"
    lines = [
        "# Trading v0.4 Acceptance Report",
        "",
        f"Generated: {_now_iso()}",
        "",
        "## Checks",
    ]
    for label, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        lines.append(f"- {status} - {label}" + (f" ({detail})" if detail else ""))
    lines.extend(
        [
            "",
            "## Proof Paths",
            f"- {FAST_GATE_REPORT_PATH.relative_to(ROOT)}",
            f"- {DAILY_READINESS_REPORT_PATH.relative_to(ROOT)}",
            f"- {ACCEPTANCE_REPORT_PATH.relative_to(ROOT)}",
            "- data/trading/events/*_tradingview_events.jsonl",
            "",
            f"FINAL VERDICT: {verdict}",
        ]
    )
    ACCEPTANCE_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return verdict


def main() -> int:
    _ensure_dirs()
    local_result = run_local_upload_engine()
    run_daily_readiness_check()
    checks = [
        ("local upload engine executed", True, local_result.status),
        ("DAILY_READINESS_REPORT.md exists", DAILY_READINESS_REPORT_PATH.exists(), ""),
    ]
    verdict = write_acceptance_report(checks)
    print(verdict)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
