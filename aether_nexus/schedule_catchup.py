"""Auto catch-up for missed daily Aether / paper slots.

Polls pipeline_health; when a lane is stale past grace, kickstarts its LaunchAgent
(if installed) then runs the lane daemon with --once.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daemon_schedule import parse_hhmm

logger = logging.getLogger("schedule_catchup")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
PAPER_DIR = REPO_ROOT / "aether-paper"
STATE_PATH = BASE_DIR / "schedule_catchup_state.json"

STALE_KEYS = (
    "stale_post_market",
    "stale_paper_daily",
)


@dataclass(frozen=True)
class LaneSpec:
    stale_key: str
    script: Path
    cwd: Path
    launch_label: str | None
    schedule_env: str
    schedule_default: str


LANES: tuple[LaneSpec, ...] = (
    LaneSpec(
        "stale_post_market",
        BASE_DIR / "post_market_summary_daemon.py",
        BASE_DIR,
        "com.demo.aether.post-market-summary",
        "POST_MARKET_SUMMARY_TIME",
        "16:40",
    ),
    LaneSpec(
        "stale_paper_daily",
        PAPER_DIR / "paper_daily_report_daemon.py",
        PAPER_DIR,
        "com.demo.aether.paper-daily",
        "PAPER_DAILY_TIME",
        "16:40",
    ),
)


_DOTENV_LOADED = False


def _load_dotenv() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    env_path = BASE_DIR / ".env"
    if not env_path.is_file():
        _DOTENV_LOADED = True
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except ImportError:
        pass
    _DOTENV_LOADED = True


def _read_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _python() -> str:
    venv = BASE_DIR / ".venv" / "bin" / "python"
    return str(venv if venv.is_file() else "python3")


def _launch_domain() -> str:
    return f"gui/{os.getuid()}"


def agent_pid(label: str) -> int | None:
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=False)
    for line in r.stdout.splitlines():
        if label not in line:
            continue
        parts = line.split()
        if len(parts) >= 1 and parts[0].isdigit():
            return int(parts[0])
    return None


def _gateway_base() -> str:
    raw = os.getenv("GRID_EVENTS", "http://127.0.0.1:8501/store/events").rstrip("/")
    if raw.endswith("/store/events"):
        return raw[: -len("/store/events")]
    return os.getenv("GARDEN_GATEWAY_URL", "http://127.0.0.1:8501").rstrip("/")


def kickstart_agent(label: str, *, kill: bool = False) -> bool:
    plist = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    if not plist.is_file():
        return False
    domain = _launch_domain()
    args = ["launchctl", "kickstart"]
    if kill:
        args.append("-k")
    args.append(f"{domain}/{label}")
    r = subprocess.run(args, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=False)
        r = subprocess.run(
            ["launchctl", "kickstart", f"{domain}/{label}"],
            capture_output=True,
            text=True,
            check=False,
        )
    return r.returncode == 0


def ensure_gateway8501(*, kickstart: bool = True) -> tuple[bool, str]:
    """8501 must be up before /store/events emit — never -k kill a live gateway pid."""
    health = f"{_gateway_base()}/health"

    def _probe() -> bool:
        try:
            with urllib.request.urlopen(health, timeout=8) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    if _probe():
        return True, "ok"

    pid = agent_pid("com.demo.grid.gateway8501")
    if pid:
        for _ in range(4):
            time.sleep(2)
            if _probe():
                return True, "ok_after_wait"
        logger.warning("8501 health failed but pid=%s — skip kill (active gateway/chat)", pid)
        return True, "ok_assume_busy"

    if not kickstart:
        return False, "gateway_down"

    logger.warning("8501 down (no pid) — starting com.demo.grid.gateway8501")
    kickstart_agent("com.demo.grid.gateway8501", kill=False)
    for wait in (5, 8, 10):
        time.sleep(wait)
        if _probe():
            return True, "recovered_after_kickstart"
    return False, "gateway_still_down_after_kickstart"


def _cooldown_active(day: str, lane_key: str, *, retry_minutes: int) -> bool:
    state = _read_state()
    row = (state.get(day) or {}).get(lane_key) or {}
    last = row.get("last_attempt_ts")
    if not last or row.get("ok"):
        return False
    try:
        ts = dt.datetime.fromisoformat(str(last))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    age = dt.datetime.now(dt.timezone.utc) - ts.astimezone(dt.timezone.utc)
    return age.total_seconds() < retry_minutes * 60


def _record_attempt(day: str, lane_key: str, *, ok: bool, detail: str) -> None:
    state = _read_state()
    day_row = state.setdefault(day, {})
    day_row[lane_key] = {
        "last_attempt_ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "ok": ok,
        "detail": detail[:500],
    }
    _save_state(state)


def run_lane_once(spec: LaneSpec, *, timeout_sec: int = 7200) -> tuple[bool, str]:
    env = os.environ.copy()
    env.setdefault("CC_CLI_EXECUTION_FROZEN", "1")
    env.setdefault("GRID_EVENTS", "http://127.0.0.1:8501/store/events")
    ssl = subprocess.run([_python(), "-m", "certifi"], capture_output=True, text=True, check=False)
    if ssl.returncode == 0 and ssl.stdout.strip():
        env.setdefault("SSL_CERT_FILE", ssl.stdout.strip())
        env.setdefault("REQUESTS_CA_BUNDLE", ssl.stdout.strip())
    cmd = [_python(), str(spec.script), "--once"]
    logger.info("catchup exec: %s (cwd=%s)", " ".join(cmd), spec.cwd)
    proc = subprocess.run(
        cmd,
        cwd=str(spec.cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    tail = (proc.stderr or proc.stdout or "")[-800:]
    if proc.returncode == 0:
        return True, tail
    return False, f"exit={proc.returncode} {tail}"


def catchup_pass(*, grace_minutes: int | None = None, retry_minutes: int | None = None) -> dict[str, Any]:
    """One catch-up sweep. Returns actions taken."""
    _load_dotenv()
    grace = grace_minutes if grace_minutes is not None else int(os.getenv("SCHEDULE_CATCHUP_GRACE_MIN", "3"))
    retry = retry_minutes if retry_minutes is not None else int(os.getenv("SCHEDULE_CATCHUP_RETRY_MIN", "10"))

    gw_ok, gw_detail = ensure_gateway8501()
    actions: list[dict[str, Any]] = []
    if not gw_ok:
        logger.error("catchup blocked — gateway8501 unavailable (%s)", gw_detail)
        return {
            "today": dt.datetime.now().strftime("%Y-%m-%d"),
            "actions": [{"lane": "gateway8501", "action": "kickstart", "ok": False, "detail": gw_detail}],
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "gateway_ok": False,
        }
    if gw_detail != "ok":
        actions.append({"lane": "gateway8501", "action": "kickstart", "ok": True, "detail": gw_detail})

    from aether_shared import EST
    from pipeline_health import pipeline_health

    ph = pipeline_health()
    today = str(ph.get("today"))
    now_est = dt.datetime.now(EST)

    for spec in LANES:
        if not ph.get(spec.stale_key):
            continue
        schedule = os.getenv(spec.schedule_env, spec.schedule_default)
        h, m = parse_hhmm(schedule)
        from daemon_schedule import minutes_past_slot

        if minutes_past_slot(now_est, h, m) < grace:
            continue
        if _cooldown_active(today, spec.stale_key, retry_minutes=retry):
            continue

        if spec.launch_label and agent_pid(spec.launch_label) is None:
            logger.warning("lane %s stale — kickstart %s", spec.stale_key, spec.launch_label)
            kickstart_agent(spec.launch_label)
            time.sleep(45)
            ph = pipeline_health()
            if not ph.get(spec.stale_key):
                _record_attempt(today, spec.stale_key, ok=True, detail="recovered after kickstart")
                actions.append({"lane": spec.stale_key, "action": "kickstart", "ok": True})
                continue

        ok, detail = run_lane_once(spec)
        _record_attempt(today, spec.stale_key, ok=ok, detail=detail)
        actions.append({"lane": spec.stale_key, "action": "once", "ok": ok, "detail": detail[:200]})
        logger.info("catchup %s ok=%s", spec.stale_key, ok)

    verify_result: dict[str, Any] | None = None
    try:
        from daily_stack_verify import verify_and_alert

        verify_result = verify_and_alert(trade_date=today, notify=True)
        actions.append(
            {
                "lane": "daily_stack_verify",
                "action": "verify",
                "ok": bool(verify_result.get("ok")),
                "detail": ",".join(
                    c["name"] for c in (verify_result.get("checks") or []) if not c.get("ok")
                )[:200]
                or "pass",
            }
        )
    except Exception as exc:
        logger.exception("daily stack verify failed: %s", exc)
        actions.append({"lane": "daily_stack_verify", "action": "verify", "ok": False, "detail": str(exc)[:200]})

    out: dict[str, Any] = {
        "today": today,
        "actions": actions,
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "gateway_ok": True,
    }
    if verify_result is not None:
        out["daily_stack_ok"] = verify_result.get("ok")
    return out
