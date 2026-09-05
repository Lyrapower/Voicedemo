"""Automated daily stack QA — runs from schedule_catchup; no manual checks."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sqlite3
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("daily_stack_verify")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
STORE_DB = REPO_ROOT / "grid-sovereign-runtime" / "data" / "grid_store.db"
STATE_PATH = BASE_DIR / "daily_stack_verify_state.json"
EST = ZoneInfo("America/New_York")
VERIFY_COOLDOWN_MIN = int(os.getenv("DAILY_STACK_VERIFY_COOLDOWN_MIN", "30"))


def offpool_coach_required() -> bool:
    """Fable offpool_coach intentionally retired 2026-07-23 (_sealed/ab_2026-07).

    Missing coach store must NEVER hard-fail the whole daily stack / catchup QA.
    Set OFFPOOL_COACH_REQUIRED=1 only if coach is deliberately revived.
    """
    raw = (os.getenv("OFFPOOL_COACH_REQUIRED") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    status = (os.getenv("OFFPOOL_COACH_STATUS") or "retired").strip().lower()
    if status in ("retired", "disabled", "off", "sealed", "0", "false"):
        return False
    # default: not required (coach start scripts hard-exit since 2026-07-23)
    return False


def _gateway_base() -> str:
    raw = os.getenv("GRID_EVENTS", "http://127.0.0.1:8501/store/events").rstrip("/")
    if raw.endswith("/store/events"):
        return raw[: -len("/store/events")]
    return os.getenv("GARDEN_GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")


def _today_est() -> str:
    return dt.datetime.now(EST).date().isoformat()


def _read_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _http_ok(url: str, *, timeout: float = 4.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=_ssl_context()) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _launchd_running(label: str) -> bool:
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=False)
    for line in r.stdout.splitlines():
        if label not in line:
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[0].lstrip("-").isdigit() and parts[1] != "-15":
            return True
        if len(parts) >= 2 and parts[0].isdigit():
            return True
    r2 = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return "state = running" in (r2.stdout or "")


def _tailscale_health() -> tuple[bool, str]:
    if not shutil_which("tailscale"):
        return True, "tailscale_cli_missing_skipped"
    try:
        proc = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if proc.returncode != 0:
            return True, "tailscale_status_unavailable_skipped"
        data = json.loads(proc.stdout or "{}")
        host = str((data.get("Self") or {}).get("DNSName") or "").rstrip(".")
        if not host:
            return True, "tailscale_dns_missing_skipped"
        if _http_ok(f"https://{host}/health"):
            return True, host
        return False, f"tailscale_serve_down:{host}"
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError) as exc:
        return True, f"tailscale_check_skipped:{exc}"


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def _store_count(kind: str, *, trade_date: str, window: str | None = None) -> int:
    if not STORE_DB.is_file():
        return 0
    start = dt.datetime.fromisoformat(trade_date).replace(tzinfo=EST).timestamp()
    end = start + 86400.0
    with sqlite3.connect(str(STORE_DB)) as conn:
        if kind == "aether_scan":
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE source='aether' AND kind=? AND ts>=? AND ts<?",
                (kind, start, end),
            ).fetchone()
        elif window:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE source='aether' AND kind=? "
                "AND json_extract(payload,'$.date')=? AND json_extract(payload,'$.window')=?",
                (kind, trade_date, window),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE source='aether' AND kind=? "
                "AND json_extract(payload,'$.date')=?",
                (kind, trade_date),
            ).fetchone()
    return int(row[0] if row else 0)


def run_daily_stack_verify(*, trade_date: str | None = None) -> dict[str, Any]:
    """Return {ok, checks[], failures[], trade_date}. Never raises."""
    trade_date = trade_date or _today_est()
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    warnings: list[str] = []

    def check(name: str, ok: bool, detail: str = "", *, hard: bool = True) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "hard": hard})
        if not ok and hard:
            failures.append(f"{name}: {detail or 'fail'}")
        elif not ok:
            warnings.append(f"{name}: {detail or 'warn'}")

    check("gateway8501_health", _http_ok(f"{_gateway_base()}/health"), _gateway_base())
    check("lm_studio_1234", _http_ok("http://127.0.0.1:1234/v1/models"), ":1234")
    check(
        "launchd_gateway8501",
        _launchd_running("com.demo.grid.gateway8501"),
        "com.demo.grid.gateway8501",
    )

    ts_ok, ts_detail = _tailscale_health()
    check("tailscale_serve", ts_ok, ts_detail)

    now_est = dt.datetime.now(EST)
    trade_d = dt.date.fromisoformat(trade_date)
    # After AM BFS/pool window (~07:00 ET) require scan; before that, warn only.
    scan_due = (now_est.date() > trade_d) or (
        now_est.date() == trade_d and (now_est.hour, now_est.minute) >= (7, 30)
    )
    # Post-market ground after 16:45 ET
    post_due = (now_est.date() > trade_d) or (
        now_est.date() == trade_d and (now_est.hour, now_est.minute) >= (16, 45)
    )

    if trade_d.weekday() < 5:
        scan_n = _store_count("aether_scan", trade_date=trade_date)
        check(
            "store_aether_scan",
            scan_n >= 1,
            f"count={scan_n}",
            hard=scan_due,
        )

        from post_market_summary_daemon import ground_from_store_scan

        ground = ground_from_store_scan(trade_date)
        check(
            "post_market_store_ground",
            bool(ground.get("top_symbol")),
            str(ground.get("top_symbol") or "empty"),
            hard=post_due,
        )

        trial_start = os.getenv("OFFPOOL_COACH_TRIAL_START", "2026-07-17").strip()
        if trade_date >= trial_start:
            coach_req = offpool_coach_required()
            for window in ("PREMARKET", "EXECUTION"):
                n = _store_count("aether_offpool_coach", trade_date=trade_date, window=window)
                detail = f"count={n}" + (
                    "" if coach_req else " · coach retired (OFFPOOL_COACH_REQUIRED≠1)"
                )
                check(
                    f"store_offpool_coach_{window}",
                    n >= 1,
                    detail,
                    hard=coach_req,
                )

        grid_body = _fetch_bytes(f"{_gateway_base()}/app/grid.html")
        grid_ok = _http_ok(f"{_gateway_base()}/app/grid.html") and (
            b"PAGE_VER=" in grid_body or b"ui " in grid_body or b"laneHud" in grid_body
        )
        check("grid_html_served", grid_ok, "grid PAGE_VER/laneHud")
        check("aether_html_served", _http_ok(f"{_gateway_base()}/app/aether.html"), "aether.html")

    ok = not failures
    return {
        "ok": ok,
        "trade_date": trade_date,
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
        "offpool_coach_required": offpool_coach_required(),
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _fetch_bytes(url: str, *, limit: int = 65536) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=8, context=_ssl_context()) as resp:
            return resp.read(limit)
    except (urllib.error.URLError, TimeoutError, OSError):
        return b""


def maybe_alert_verify_result(result: dict[str, Any]) -> bool:
    """Notify on new failure; suppress repeat alerts within cooldown. Returns True if alerted."""
    if result.get("ok"):
        state = _read_state()
        if state.get("last_fail_date") == result.get("trade_date"):
            state.pop("last_fail_date", None)
            state.pop("last_alert_ts", None)
            state["last_pass_ts"] = result.get("checked_at")
            _write_state(state)
        return False

    state = _read_state()
    now = dt.datetime.now(dt.timezone.utc)
    last_alert = state.get("last_alert_ts")
    same_day = state.get("last_fail_date") == result.get("trade_date")
    if last_alert and same_day:
        try:
            prev = dt.datetime.fromisoformat(str(last_alert))
            if prev.tzinfo is None:
                prev = prev.replace(tzinfo=dt.timezone.utc)
            age_min = (now - prev.astimezone(dt.timezone.utc)).total_seconds() / 60.0
            if age_min < VERIFY_COOLDOWN_MIN:
                return False
        except ValueError:
            pass

    fails = result.get("failures") or []
    msg = "🔴 Grid/Aether stack QA FAIL\n" + "\n".join(f"· {f}" for f in fails[:8])
    try:
        from aether_shared import send_notification

        send_notification(msg[:3500])
    except Exception as exc:
        logger.warning("verify alert send failed: %s", exc)

    state["last_fail_date"] = result.get("trade_date")
    state["last_alert_ts"] = now.isoformat()
    state["last_failures"] = fails[:20]
    _write_state(state)
    logger.error("daily stack verify FAIL: %s", fails)
    return True


def verify_and_alert(*, trade_date: str | None = None, notify: bool = True) -> dict[str, Any]:
    result = run_daily_stack_verify(trade_date=trade_date)
    if result.get("ok"):
        logger.info("daily stack verify PASS (%s)", result.get("trade_date"))
    else:
        logger.error("daily stack verify FAIL: %s", result.get("failures"))
        if notify:
            maybe_alert_verify_result(result)
    return result
