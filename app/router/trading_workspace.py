from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
COMPILED_TRADING = ROOT / "knowledge" / "compiled" / "WORKSPACE_trading.md"
BOTTLENECK_HEADER = "## Bottleneck Ledger (Top 3)"


def active_constraints_present_from_compiled(path: Path = COMPILED_TRADING) -> bool:
    """True if compiled WORKSPACE_trading.md Bottleneck Ledger contains any `- state: active` row."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    if BOTTLENECK_HEADER not in text:
        return False
    start = text.index(BOTTLENECK_HEADER)
    end_mark = text.find("- trading_permission:", start)
    section = text[start:end_mark] if end_mark != -1 else text[start:]
    return "- state: active" in section
DATA_DIR = ROOT / "data" / "trading"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
RAW_DAYS = 7
SNAPSHOTS_KEEP = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp() -> str:
    return _now().strftime("%Y%m%dT%H%M%SZ")


def _ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _delete_old_raw() -> list[str]:
    cutoff = _now() - timedelta(days=RAW_DAYS)
    deleted: list[str] = []
    for path in sorted(RAW_DIR.glob("*.json")):
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if modified < cutoff:
            deleted.append(str(path.relative_to(ROOT)))
            path.unlink(missing_ok=True)
    return deleted


def _cap_snapshots() -> list[str]:
    deleted: list[str] = []
    snapshots = sorted(SNAPSHOTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in snapshots[SNAPSHOTS_KEEP:]:
        deleted.append(str(path.relative_to(ROOT)))
        path.unlink(missing_ok=True)
    return deleted


def update_trading_workspace_state() -> dict[str, Any]:
    _ensure_dirs()
    spec_path = ROOT / "specs" / "trading_module_spec.md"
    proof_path = ROOT / "deliver" / "proof" / "trading" / "ACCEPTANCE_REPORT.md"
    radar_settings_path = ROOT / "data" / "radar_settings.json"
    radar_db_path = ROOT / "data" / "radarbrief_v1.sqlite3"

    market_data_available = radar_db_path.exists()
    current_regime = "unknown"
    current_narrative = "none"
    decision = "PASS"
    missing_fields: list[str] = []

    if not market_data_available:
        missing_fields.append("market_snapshot")
    if current_regime == "unknown":
        missing_fields.append("regime_signal")
    if current_narrative == "none":
        missing_fields.append("narrative_signal")

    raw_payload = {
        "updated_at": _now_iso(),
        "source_artifacts": {
            "spec_path": str(spec_path.relative_to(ROOT)),
            "proof_path": str(proof_path.relative_to(ROOT)),
            "radar_settings_path": str(radar_settings_path.relative_to(ROOT)),
            "radar_db_path": str(radar_db_path.relative_to(ROOT)),
        },
        "radar_settings": _read_json(radar_settings_path),
        "market_data_available": market_data_available,
        "current_regime": current_regime,
        "current_active_narrative": current_narrative,
        "decision": decision,
        "missing_fields": missing_fields,
    }

    raw_path = RAW_DIR / f"ingest_{_stamp()}.json"
    raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    deleted_raw = _delete_old_raw()

    active_constraints_present = active_constraints_present_from_compiled()
    normalized_payload = {
        "latest_local_data_update": raw_payload["updated_at"],
        "data_freshness_status": "local-only / no live market payload" if not market_data_available else "local market payload present",
        "raw_path": str(raw_path.relative_to(ROOT)),
        "normalized_path": str((NORMALIZED_DIR / "current.json").relative_to(ROOT)),
        "snapshots_path": str(SNAPSHOTS_DIR.relative_to(ROOT)),
        "raw_days": RAW_DAYS,
        "snapshots_keep": SNAPSHOTS_KEEP,
        "retention_status": "enforced during ingest/update flow",
        "deleted_raw_files": deleted_raw,
        "current_regime": current_regime,
        "current_active_narrative": current_narrative,
        "decision": decision,
        "missing_fields": missing_fields,
        "weekly_trade_count": 0,
        "trading_permission": "allowed_only_if_active_constraint_required",
        "trading_permission_active_required": True,
        "active_constraints_present": active_constraints_present,
        "permission_granted": bool(active_constraints_present),
    }

    normalized_path = NORMALIZED_DIR / "current.json"
    normalized_path.write_text(json.dumps(normalized_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    snapshot_path = SNAPSHOTS_DIR / f"snapshot_{_stamp()}.json"
    snapshot_path.write_text(json.dumps(normalized_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    deleted_snapshots = _cap_snapshots()

    normalized_payload["deleted_snapshot_files"] = deleted_snapshots
    normalized_path.write_text(json.dumps(normalized_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    raw_files = sorted(RAW_DIR.glob("*.json"))
    snapshot_files = sorted(SNAPSHOTS_DIR.glob("*.json"))
    normalized_payload["raw_dir"] = str(RAW_DIR.relative_to(ROOT))
    normalized_payload["raw_file_count"] = len(raw_files)
    normalized_payload["snapshot_count"] = len(snapshot_files)
    normalized_payload["latest_snapshot_path"] = str(snapshot_path.relative_to(ROOT))
    normalized_payload["market_data_available"] = market_data_available
    normalized_path.write_text(json.dumps(normalized_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized_payload
