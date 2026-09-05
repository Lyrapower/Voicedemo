"""R1 — structured post-market fact pack (same spec for Grid + Sonnet review)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent
JOURNAL_GRID = BASE / "traces" / "premarket_ab" / "journal_grid.jsonl"
JOURNAL_SONNET = BASE / "traces" / "premarket_ab" / "journal_sonnet.jsonl"
FILTER_DIR = BASE / "logs" / "rejections"
FILTER_DIR_LEGACY = BASE / "dryrun_state" / "rejection_logs"


def _rejection_log_dirs() -> list[Path]:
    """Writer (aether_dryrun) uses logs/rejections; legacy path kept as fallback."""
    out: list[Path] = []
    for p in (FILTER_DIR, FILTER_DIR_LEGACY):
        if p.is_dir() and p not in out:
            out.append(p)
    return out


def _journal_rows(trade_date: str, chain: str) -> list[dict[str, Any]]:
    path = JOURNAL_GRID if chain == "grid" else JOURNAL_SONNET
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("date") == trade_date:
            out.append(row)
    return out


def _filter_counts(trade_date: str) -> dict[str, int]:
    """Best-effort kill counts from latest rejection summary."""
    counts: dict[str, int] = {}
    files: list[Path] = []
    for d in _rejection_log_dirs():
        files.extend(sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for fp in files[:6]:
        name_hit = trade_date in fp.name
        for line in fp.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]:
            if not name_hit and trade_date not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rule = str(row.get("kill_rule") or row.get("reason") or "other")
            counts[rule] = counts.get(rule, 0) + 1
    return counts


def _paper_positions() -> list[dict[str, Any]]:
    try:
        from paper.summary import lane_row

        rows: list[dict[str, Any]] = []
        for lane in ("equity", "sonnet_earnings"):
            snap = lane_row(lane)
            if snap.get("status") == "uninitialized":
                continue
            for sym in snap.get("positions") or []:
                rows.append({"lane": lane, "sym": sym, "state": "open_mock"})
        return rows
    except Exception:
        return []


def build_fact_pack(
    trade_date: str,
    *,
    ground: dict[str, Any] | None = None,
    premarket_ab: dict[str, Any] | None = None,
    deepseek_performance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Precomputed facts — both chains receive identical envelope."""
    grid_rows = _journal_rows(trade_date, "grid")
    sonnet_rows = _journal_rows(trade_date, "sonnet")
    signals: list[dict[str, Any]] = []
    for chain, rows in (("grid", grid_rows), ("sonnet", sonnet_rows)):
        for r in rows:
            signals.append(
                {
                    "chain": chain,
                    "sym": r.get("sym"),
                    "dir": r.get("dir"),
                    "confidence": r.get("confidence"),
                    "state": "signal",
                    "note": r.get("note"),
                }
            )
    positions = _paper_positions()
    closed_today = 0  # report-only mock — no IB closes
    pack: dict[str, Any] = {
        "schema": "postmarket_fact_pack/v1",
        "trade_date": trade_date,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "zero_realized_close": True,
        "zero_close_statement": "今日零平仓，无已实现收益；禁止编造胜率或平仓统计。",
        "win_rate_available": False,
        "signals": signals,
        "open_positions": positions,
        "closed_today_count": closed_today,
        "filter_kill_counts": _filter_counts(trade_date),
        "scan_top": (ground or {}).get("parsed_score_rows") or [],
        "premarket_ab": {
            "grid_n": (premarket_ab or {}).get("grid_n", 0),
            "sonnet_n": (premarket_ab or {}).get("sonnet_n", 0),
            "warmup": (premarket_ab or {}).get("warmup"),
            "ab_ledger_start": (premarket_ab or {}).get("ab_ledger_start"),
        },
        "deepseek_performance": _deepseek_fact_slice(deepseek_performance),
    }
    return pack


def _deepseek_fact_slice(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {}
    off = summary.get("offpool") or {}
    pre = summary.get("premarket") or {}
    daily_off = off.get("daily") or {}
    ds = daily_off.get("deepseek-v4") or {}
    sn = daily_off.get("sonnet-4.6") or {}
    rolling = off.get("rolling") or {}
    ds_roll = rolling.get("deepseek-v4") or {}
    return {
        "observation_days": summary.get("observation_days"),
        "offpool_deepseek_items": ds.get("item_count"),
        "offpool_sonnet_items": sn.get("item_count"),
        "offpool_deepseek_fabricated": ds.get("fabricated_count"),
        "offpool_sonnet_fabricated": sn.get("fabricated_count"),
        "rolling_fabrication_rate_deepseek": ds_roll.get("fabrication_rate"),
        "rolling_fabrication_rate_sonnet": (rolling.get("sonnet-4.6") or {}).get("fabrication_rate"),
        "premarket_windows": {
            w: (pre.get("daily") or {}).get(w, {}).get("item_count")
            for w in ("premarket", "intraday")
        },
        "report_only": True,
    }


def format_fact_pack_for_journal(pack: dict[str, Any]) -> str:
    lines = [
        "=== FACT PACK (precomputed, do not invent stats) ===",
        pack.get("zero_close_statement", ""),
        f"signals: grid={sum(1 for s in pack.get('signals', []) if s.get('chain')=='grid')} "
        f"sonnet={sum(1 for s in pack.get('signals', []) if s.get('chain')=='sonnet')}",
        f"open_mock_positions: {len(pack.get('open_positions') or [])}",
        f"closed_today: {pack.get('closed_today_count', 0)}",
    ]
    kills = pack.get("filter_kill_counts") or {}
    if kills:
        top = ", ".join(f"{k}={v}" for k, v in sorted(kills.items(), key=lambda x: -x[1])[:8])
        lines.append(f"filter_kills: {top}")
    scan = pack.get("scan_top") or []
    if scan:
        tops = ", ".join(f"{s}({sc})" for s, sc in scan[:6])
        lines.append(f"scan_top: {tops}")
    ab = pack.get("premarket_ab") or {}
    if ab.get("warmup"):
        lines.append(f"premarket_ab: warmup · 30d starts {ab.get('ab_ledger_start')}")
    ds = pack.get("deepseek_performance") or {}
    if ds.get("offpool_deepseek_items") is not None or ds.get("offpool_sonnet_items") is not None:
        lines.append(
            f"deepseek_offpool: DS {ds.get('offpool_deepseek_items')}条 硬凑{ds.get('offpool_deepseek_fabricated')} · "
            f"SN {ds.get('offpool_sonnet_items')}条 硬凑{ds.get('offpool_sonnet_fabricated')}"
        )
    lines.append("=== END FACT PACK ===")
    return "\n".join(lines)


def format_fact_pack_ui_lines(pack: dict[str, Any]) -> list[str]:
    """Compact lines for R1 side-by-side UI — each stat traceable."""
    lines = [
        pack.get("zero_close_statement") or "",
        f"signals grid={sum(1 for s in pack.get('signals', []) if s.get('chain')=='grid')} "
        f"sonnet={sum(1 for s in pack.get('signals', []) if s.get('chain')=='sonnet')}",
        f"open_mock_positions={len(pack.get('open_positions') or [])}",
        f"closed_today={pack.get('closed_today_count', 0)}",
        f"win_rate_available={pack.get('win_rate_available', False)}",
    ]
    ab = pack.get("premarket_ab") or {}
    if ab.get("warmup"):
        lines.append(f"premarket_ab: warmup · 不入册 · 30d starts {ab.get('ab_ledger_start')}")
    kills = pack.get("filter_kill_counts") or {}
    if kills:
        top = ", ".join(f"{k}={v}" for k, v in sorted(kills.items(), key=lambda x: -x[1])[:6])
        lines.append(f"filter_kills: {top}")
    return [ln for ln in lines if ln]


def fallback_brief_body(
    pack: dict[str, Any],
    *,
    final: dict[str, Any] | None = None,
) -> str:
    """Store / Aether app body when 8501 compile blocked or drifted."""
    fin = final or {}
    sym = str(fin.get("top_symbol") or "").strip().upper()
    cc = int(fin.get("candidate_count") or 0)
    score = float(fin.get("top_score") or 0)
    lines: list[str] = []
    if sym:
        lines.append(
            f"今日做对：盘前 journal {cc} 候选 · top {sym}"
            + (f" ({score:.1f})" if score else "")
            + "。"
        )
    else:
        lines.append("今日做对：fact pack 已同步，无 scan top。")
    lines.append("今日做错：盘后 compile 未通过 gateway（blocked/格式），以下为 fact pack 摘要。")
    lines.append("次日关注：")
    picks = [s for s in (pack.get("signals") or []) if s.get("chain") == "grid"][:3]
    if not picks:
        picks = (pack.get("signals") or [])[:3]
    for s in picks:
        sym_s = str(s.get("sym") or "").upper()
        d = int(s.get("dir") or 0)
        direction = "多" if d > 0 else "空" if d < 0 else "观察"
        conf = str(s.get("confidence") or "观察")
        note = str(s.get("note") or "").split("|")[0][:100]
        risk = note.split("风险：")[-1][:80] if "风险：" in note else "见盘前 note"
        why = note.split("风险：")[0][:80] if note else "盘前信号延续"
        lines.append(
            f"- 标的：{sym_s}|方向：{direction}|为什么明天：{why}|风险：{risk}|置信：[{conf}]"
        )
    if pack.get("zero_close_statement"):
        lines.append("")
        lines.append(str(pack["zero_close_statement"]))
    return "\n".join(lines).strip()
