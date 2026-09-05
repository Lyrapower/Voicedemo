"""Paper 多 lane 路径 —— equity / crypto_rules / crypto_cli 物理隔离。"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from .account import PaperAccount, Position, RiskLimits

BASE = Path(__file__).resolve().parent.parent
STATE_DIR = BASE / "state"

# equity ← Grid scan; crypto_rules ← 动量规则; crypto_cli ← CC CLI sonnet (A/B 对照)
# sonnet_earnings ← 财报前期权 lane (report-only, isolated)
LANE_PATHS: dict[str, dict[str, Path]] = {
    "equity": {
        "account": STATE_DIR / "account.json",
        "decisions": STATE_DIR / "decisions.jsonl",
        "heartbeat": STATE_DIR / "heartbeat.json",
        "experiment": STATE_DIR / "experiment.json",
        "inbox": STATE_DIR / "signal_inbox.jsonl",
        "processed": STATE_DIR / "processed_signals.json",
    },
    "crypto_rules": {
        "account": STATE_DIR / "account_crypto_rules.json",
        "decisions": STATE_DIR / "decisions_crypto_rules.jsonl",
        "heartbeat": STATE_DIR / "heartbeat_crypto_rules.json",
        "experiment": STATE_DIR / "experiment_crypto_rules.json",
        "inbox": STATE_DIR / "signal_inbox_crypto_rules.jsonl",
        "processed": STATE_DIR / "processed_signals_crypto_rules.json",
    },
    "crypto_cli": {
        "account": STATE_DIR / "account_crypto_cli.json",
        "decisions": STATE_DIR / "decisions_crypto_cli.jsonl",
        "heartbeat": STATE_DIR / "heartbeat_crypto_cli.json",
        "experiment": STATE_DIR / "experiment_crypto_cli.json",
        "inbox": STATE_DIR / "signal_inbox_crypto_cli.jsonl",
        "processed": STATE_DIR / "processed_signals_crypto_cli.json",
    },
    "sonnet_earnings": {
        "account": STATE_DIR / "account_sonnet_earnings.json",
        "decisions": STATE_DIR / "decisions_sonnet_earnings.jsonl",
        "heartbeat": STATE_DIR / "heartbeat_sonnet_earnings.json",
        "experiment": STATE_DIR / "experiment_sonnet_earnings.json",
        "inbox": STATE_DIR / "signal_inbox_sonnet_earnings.jsonl",
        "processed": STATE_DIR / "processed_signals_sonnet_earnings.json",
        "trades": STATE_DIR / "sonnet_earnings_trades.jsonl",
    },
}

# legacy alias: old "crypto" lane files → crypto_rules
LANE_ALIASES = {"crypto": "crypto_rules"}

PAPER_TICK_LANES = ("equity", "crypto_rules", "crypto_cli", "sonnet_earnings")
CRYPTO_AB_LANES = ("crypto_rules", "crypto_cli")

# lane = owner × asset_class — 汇总行必须显式标 aggregation_scope
LANE_REGISTRY: dict[str, dict[str, str]] = {
    "equity": {
        "id": "equity",
        "owner": "grid",
        "asset_class": "equity_underlying",
        "label": "grid_aster_paper_month",
    },
    "crypto_rules": {
        "id": "crypto_rules",
        "owner": "grid",
        "asset_class": "crypto_spot",
        "label": "crypto_paper_ab_rules",
    },
    "crypto_cli": {
        "id": "crypto_cli",
        "owner": "sonnet",
        "asset_class": "crypto_spot",
        "label": "crypto_paper_ab_sonnet46",
    },
    "sonnet_earnings": {
        "id": "sonnet_earnings",
        "owner": "sonnet",
        "asset_class": "equity_options",
        "label": "sonnet_earnings_paper",
    },
}
CRYPTO_AB_UNIVERSE = ["BTC-USD", "ETH-USD", "SOL-USD"]
CRYPTO_FEED_DEFAULT = os.getenv("CRYPTO_FEED", "coinbase")
# A/B 公平性契约 — 开跑前写死; 页面与 emit 引用此常量, 禁止 lane 分叉
AB_FEE_SLIPPAGE_MODEL = (
    "paper_spot: fill at mark/ref_price, zero explicit fee/slippage layer (engine.enter @ mark)"
)
AB_BG_ANCHOR_NOTE = (
    "BTC-USD buy-and-hold: Coinbase spot; btc_anchor_price captured at lane init; "
    "return_pct_background = lane_return_pct - btc_buyhold_return_pct (beat BTC = positive bg)"
)


def ab_contract_template(lane: str) -> dict[str, Any]:
    return {
        "lane": resolve_lane(lane),
        "feed": f"{CRYPTO_FEED_DEFAULT} primary, kraken fallback",
        "fee_slippage_model": AB_FEE_SLIPPAGE_MODEL,
        "tradable_universe": list(CRYPTO_AB_UNIVERSE),
        "bg_anchor": AB_BG_ANCHOR_NOTE,
        "bg_formula": "return_pct_background = lane_return_pct - btc_buyhold_return_pct",
        "isolated_ledgers": True,  # INVARIANT: A/B lanes never merge accounts or PnL
    }


def is_lane_initialized(lane: str) -> bool:
    return lane_paths(lane)["account"].exists()


def init_sonnet_earnings_lane(*, days: int = 30, start_equity: float = 1000.0) -> dict:
    """E2 — explicit sonnet_earnings paper init (options lane, isolated ledger)."""
    lane = "sonnet_earnings"
    ensure_state_dir()
    acc = PaperAccount(cash=start_equity, start_equity=start_equity)
    save_account(acc, lane=lane)
    exp = init_experiment(days=days, start_equity=start_equity, lane=lane)
    exp["status"] = "ready"
    exp["asset_class"] = "equity_options"
    exp["contract_style"] = "single_leg_call"
    atomic_write_json(lane_paths(lane)["experiment"], exp)
    return exp


def init_crypto_lane(*, lane: str, days: int = 30, start_equity: float = 1000.0) -> dict:
    """Explicit crypto lane init — cli 仅在 09:10 daemon 调用; 禁止 paper_daemon 偷跑 $1000。"""
    from . import crypto_feed

    lane = resolve_lane(lane)
    ensure_state_dir()
    acc = PaperAccount(cash=start_equity, start_equity=start_equity)
    save_account(acc, lane=lane)
    exp = init_experiment(days=days, start_equity=start_equity, lane=lane)
    btc = crypto_feed.spot_price("BTC-USD", prefer=CRYPTO_FEED_DEFAULT)
    if btc:
        exp["btc_anchor_price"] = btc
    exp["ab_contract"] = ab_contract_template(lane)
    exp["status"] = "ready"
    atomic_write_json(lane_paths(lane)["experiment"], exp)
    return exp

# backwards compat
ACCOUNT_PATH = LANE_PATHS["equity"]["account"]
DECISIONS_PATH = LANE_PATHS["equity"]["decisions"]
HEARTBEAT_PATH = LANE_PATHS["equity"]["heartbeat"]
EXPERIMENT_PATH = LANE_PATHS["equity"]["experiment"]
INBOX_PATH = LANE_PATHS["equity"]["inbox"]
PROCESSED_PATH = LANE_PATHS["equity"]["processed"]


def resolve_lane(lane: str) -> str:
    return LANE_ALIASES.get(lane, lane)


def lane_paths(lane: str = "equity") -> dict[str, Path]:
    lane = resolve_lane(lane)
    return LANE_PATHS.get(lane, LANE_PATHS["equity"])


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (BASE / "reports").mkdir(exist_ok=True)


def atomic_write_json(path: Path, data: Any) -> None:
    ensure_state_dir()
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_jsonl(path: Path, row: dict) -> None:
    ensure_state_dir()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    skipped = 0
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    # M9: surface corrupt lines instead of silent skip — decision
                    # history data loss was invisible. Log path, line number, snippet.
                    skipped += 1
                    if skipped <= 5:
                        logger.warning(
                            "read_jsonl corrupt line skipped %s:%d: %s (snippet=%r)",
                            path, lineno, exc, line[:120],
                        )
    if skipped:
        logger.warning("read_jsonl %s: %d corrupt line(s) skipped total", path, skipped)
    return rows


def account_to_dict(acc: PaperAccount) -> dict:
    return {
        "mode": acc.mode,
        "cash": acc.cash,
        "start_equity": acc.start_equity,
        "risk": asdict(acc.risk),
        "positions": {sym: asdict(pos) for sym, pos in acc.positions.items()},
    }


def account_from_dict(d: dict) -> PaperAccount:
    risk = RiskLimits(**(d.get("risk") or {}))
    positions = {sym: Position(**row) for sym, row in (d.get("positions") or {}).items()}
    return PaperAccount(
        mode=d.get("mode", "paper"),
        cash=float(d.get("cash", 1000.0)),
        start_equity=float(d.get("start_equity", 1000.0)),
        positions=positions,
        risk=risk,
    )


def load_account(lane: str = "equity") -> PaperAccount | None:
    path = lane_paths(lane)["account"]
    if not path.exists():
        # migrate legacy crypto account file
        if resolve_lane(lane) == "crypto_rules":
            legacy = STATE_DIR / "account_crypto.json"
            if legacy.exists() and not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                legacy.replace(path)
        if not path.exists():
            return None
    with open(path, encoding="utf-8") as f:
        return account_from_dict(json.load(f))


def save_account(acc: PaperAccount, lane: str = "equity") -> None:
    atomic_write_json(lane_paths(lane)["account"], account_to_dict(acc))


def load_processed(lane: str = "equity") -> set[str]:
    path = lane_paths(lane)["processed"]
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return set(data if isinstance(data, list) else [])


def save_processed(keys: set[str], lane: str = "equity") -> None:
    atomic_write_json(lane_paths(lane)["processed"], sorted(keys)[-500:])


def load_experiment(lane: str = "equity") -> dict:
    path = lane_paths(lane)["experiment"]
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def init_experiment(*, days: int = 30, start_equity: float = 1000.0, lane: str = "equity") -> dict:
    import datetime as dt

    lane = resolve_lane(lane)
    now = dt.datetime.now(dt.timezone.utc)
    meta = {
        "equity": ("grid_aster_paper_month", "equity_underlying", "Grid/Aster scan signals"),
        "crypto_rules": (
            "crypto_paper_ab_rules",
            "crypto_spot",
            "A/B control — 5d momentum rules (Coinbase/Kraken marks)",
        ),
        "crypto_cli": (
            "crypto_paper_ab_sonnet46",
            "crypto_spot",
            "A/B treatment — CC CLI claude-sonnet-4-6 (isolated from offpool)",
        ),
        "sonnet_earnings": (
            "sonnet_earnings_paper",
            "equity_options",
            "Report-only earnings run-up calls — never merge with premarket A/B",
        ),
    }
    label, asset, note = meta.get(lane, meta["equity"])
    exp = {
        "label": label,
        "lane": lane,
        "started_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "ends_at": (now + dt.timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "start_equity": start_equity,
        "broker_execution": False,
        "asset_class": asset,
        "note": note,
    }
    if lane.startswith("crypto"):
        from . import crypto_feed

        exp["ab_contract"] = ab_contract_template(lane)
        btc = crypto_feed.spot_price("BTC-USD", prefer=CRYPTO_FEED_DEFAULT)
        if btc:
            exp["btc_anchor_price"] = btc
    atomic_write_json(lane_paths(lane)["experiment"], exp)
    return exp


def dump_lane_registry() -> list[dict[str, Any]]:
    """B1 census — id / owner / asset_class / current equity / storage paths."""
    rows: list[dict[str, Any]] = []
    for lane, reg in LANE_REGISTRY.items():
        paths = lane_paths(lane)
        acc = load_account(lane)
        equity = None
        if acc:
            try:
                syms = set(acc.positions.keys())
                if lane.startswith("crypto"):
                    from . import crypto_feed
                    marks = crypto_feed.marks(sorted(syms), prefer=CRYPTO_FEED_DEFAULT) if syms else {}
                else:
                    from . import equity_feed
                    marks = equity_feed.marks(syms) if syms else {}
                for s, p in acc.positions.items():
                    marks.setdefault(s, p.entry_price)
                equity = round(acc.equity(marks), 2)
            except Exception:
                equity = round(acc.cash, 2)
        rows.append({
            **reg,
            "lane": lane,
            "initialized": is_lane_initialized(lane),
            "equity": equity,
            "start_equity": acc.start_equity if acc else None,
            "storage": {k: str(v) for k, v in paths.items()},
            "aggregation_scope": f"{reg['owner']}:{reg['asset_class']}",
        })
    return rows
