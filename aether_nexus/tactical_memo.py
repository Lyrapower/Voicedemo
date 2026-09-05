"""R2 — bilateral next-day tactical memos (symmetric spec, suggestion box locked)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Literal

Chain = Literal["grid", "sonnet"]

BASE = Path(__file__).resolve().parent
MEMO_DIR = BASE / "traces" / "premarket_ab" / "memos"


def memo_path(chain: Chain, trade_date: str) -> Path:
    MEMO_DIR.mkdir(parents=True, exist_ok=True)
    return MEMO_DIR / f"memo_{chain}_{trade_date}.json"


def load_memo(chain: Chain, trade_date: str) -> dict[str, Any] | None:
    p = memo_path(chain, trade_date)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_yesterday_memo(chain: Chain, trade_date: str) -> dict[str, Any] | None:
    d = dt.date.fromisoformat(trade_date) - dt.timedelta(days=1)
    return load_memo(chain, d.isoformat())


def save_memo(chain: Chain, trade_date: str, payload: dict[str, Any]) -> None:
    p = memo_path(chain, trade_date)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_memo_prompt_tail(chain: Chain, trade_date: str) -> str:
    prev = load_yesterday_memo(chain, trade_date)
    if not prev:
        return ""
    items = prev.get("items") or []
    if not items:
        return ""
    lines = [f"\n【昨日{chain.upper()}战术备忘·只读连续性】"]
    for it in items[:5]:
        lines.append(f"- {it.get('focus')} · {it.get('reason')} · 风险:{it.get('risk')}")
    lines.append("（战略参数锁死；备忘不得自动改阈值/仓位）")
    return "\n".join(lines)


def generate_memo_from_signals(
    chain: Chain,
    trade_date: str,
    *,
    signals: list[dict[str, Any]],
    filter_kills: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Deterministic scaffold — LLM compile can replace in future."""
    items: list[dict[str, Any]] = []
    for sig in signals[:5]:
        if sig.get("chain") != chain:
            continue
        sym = sig.get("sym")
        if not sym:
            continue
        items.append(
            {
                "focus": sym,
                "reason": (sig.get("note") or "")[:120],
                "risk": "filter/liquidity unchanged until owner ticket",
            }
        )
    payload = {
        "chain": chain,
        "trade_date": trade_date,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "items": items[:5],
        "suggestion_box": [],
        "suggestion_box_note": "参数变更仅主人工单+版本号；此处永不自动生效",
        "filter_kills": filter_kills or {},
    }
    save_memo(chain, trade_date, payload)
    return payload
