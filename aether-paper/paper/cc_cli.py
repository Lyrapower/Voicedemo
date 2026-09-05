"""CC CLI capture — paper crypto lane only. Isolated from aether_offpool / :8503."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)
CRYPTO_UNIVERSE = frozenset({"BTC-USD", "ETH-USD", "SOL-USD"})


@dataclass(frozen=True)
class CliLane:
    lane: str
    cli_model: str
    label: str


def default_crypto_cli_lane() -> CliLane:
    return CliLane(
        lane=os.getenv("CRYPTO_PAPER_CLI_LANE", "sonnet-4.6"),
        cli_model=os.getenv("CRYPTO_PAPER_CLI_MODEL", "claude-sonnet-4-6"),
        label=os.getenv("CRYPTO_PAPER_CLI_LABEL", "SONNET 4.6 · crypto mock"),
    )


def claude_bin() -> str:
    return os.getenv(
        "CLAUDE_BIN",
        str(Path(__file__).resolve().parents[2] / "aster_grid_v5" / ".tools" / "node_modules" / ".bin" / "claude"),
    )


def _extract_json_blob(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    m = _JSON_BLOCK.search(text)
    if m:
        text = m.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def claude_capture(prompt: str, lane: CliLane, *, timeout: int | None = None) -> tuple[str | None, dict[str, Any]]:
    timeout = timeout or int(os.getenv("CRYPTO_PAPER_CLI_TIMEOUT", "180"))
    meta: dict[str, Any] = {
        "lane": lane.lane,
        "cli_model": lane.cli_model,
        "label": lane.label,
        "resolved_models": [],
        "cost_usd": None,
        "duration_ms": None,
        "error": None,
    }
    if os.environ.get("CC_CLI_EXECUTION_FROZEN", "1") not in ("0", "false", "False"):
        logger.info("CC_CLI_EXECUTION_FROZEN=1 — crypto paper CLI read-only")
    bin_path = claude_bin()
    if not shutil.which(bin_path) and not Path(bin_path).is_file():
        meta["error"] = "claude_missing"
        return None, meta
    try:
        proc = subprocess.run(
            [bin_path, "-p", prompt, "--model", lane.cli_model, "--output-format", "json"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        meta["error"] = "timeout"
        return None, meta
    if proc.returncode != 0:
        meta["error"] = f"exit_{proc.returncode}"
        logger.error("crypto cli exit %s stderr=%s", proc.returncode, (proc.stderr or "")[:300])
        return None, meta
    try:
        envelope = json.loads(proc.stdout)
        meta["duration_ms"] = envelope.get("duration_ms")
        meta["cost_usd"] = envelope.get("total_cost_usd")
        meta["resolved_models"] = list((envelope.get("modelUsage") or {}).keys())
        text = envelope.get("result") or envelope.get("text") or envelope.get("content") or proc.stdout
        return str(text).strip(), meta
    except json.JSONDecodeError:
        meta["error"] = "bad_envelope"
        return proc.stdout.strip(), meta


def parse_crypto_cli_items(raw: str) -> list[dict[str, Any]]:
    """Parse CC CLI JSON → paper signals (crypto spot symbols only)."""
    obj = _extract_json_blob(raw)
    if not obj:
        return []
    rows = obj.get("items") or obj.get("signals") or []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("sym") or row.get("symbol") or "").upper().strip()
        if sym in ("BTC", "ETH", "SOL"):
            sym = f"{sym}-USD"
        if sym not in CRYPTO_UNIVERSE:
            continue
        want = row.get("want_pct")
        if want is None:
            conf = str(row.get("confidence") or row.get("conf") or "试探性")
            want = 0.15 if "高" in conf else 0.10 if "试探" in conf else 0.08
        want = min(float(want), 0.20)
        note = str(row.get("note") or row.get("why") or "").strip()
        if sym in seen:
            continue
        seen.add(sym)
        out.append({"sym": sym, "want_pct": want, "note": note, "dir": row.get("dir", 1)})
        if len(out) >= 3:
            break
    return out


def build_crypto_cli_prompt(*, trade_date: str, marks: dict[str, float]) -> str:
    mark_lines = "\n".join(f"  {k}: ${v:,.2f}" for k, v in sorted(marks.items()))
    universe = ", ".join(sorted(CRYPTO_UNIVERSE))
    return (
        f"Trade date: {trade_date}\n"
        "Task: crypto SPOT paper mock A/B lane (CC CLI → local paper engine only).\n"
        f"Allowed symbols ONLY: {universe}\n"
        "Current marks (public feed reference):\n"
        f"{mark_lines or '  (unavailable)'}\n\n"
        "Return ONLY valid JSON (no markdown prose):\n"
        '{"items":[{"sym":"BTC-USD","want_pct":0.10,"note":"why today + risk","dir":1}]}\n'
        "Rules: max 3 items; want_pct 0.08–0.20; symbols must be in allowed list; "
        "mock paper only — no live trading language; do not fabricate when uncertain."
    )
