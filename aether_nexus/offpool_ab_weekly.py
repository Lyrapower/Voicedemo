#!/usr/bin/env python3
"""Weekly off-pool A/B report — Sonnet 4.6 (CC CLI) vs DeepSeek V4 (Ollama cloud)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from aether_shared import EST  # noqa: E402
from offpool_ab_stats import aggregate_lane_week  # noqa: E402

TRACE_DIR = REPO_ROOT / "grid-sovereign-runtime" / "traces" / "daemon"
REPORT_DIR = REPO_ROOT / "grid-sovereign-runtime" / "traces" / "offpool_ab"
DEFAULT_LANES = ("sonnet-4.6", "deepseek-v4")


def _read_json(path: Path) -> dict | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def load_lane_traces(lane: str, *, since: dt.date, until: dt.date) -> list[dict]:
    out: list[dict] = []
    d = since
    while d <= until:
        p = TRACE_DIR / f"offpool_{lane}_{d.isoformat()}.json"
        row = _read_json(p)
        if row and not row.get("test_mode"):
            out.append(row)
        d += dt.timedelta(days=1)
    return out


def format_report(summary: dict[str, Any], *, since: dt.date, until: dt.date) -> str:
    lines = [
        f"# Off-pool A/B · {since.isoformat()} → {until.isoformat()}",
        "",
        "| Lane | Days | Items | in_pool | in_pool率 | 硬凑条数 | 硬凑率 | 硬凑天数 | 凑满3天 | 总费用 |",
        "|------|------|-------|---------|-----------|----------|--------|----------|---------|--------|",
    ]
    for lane in DEFAULT_LANES:
        s = summary.get(lane) or {}
        if not s.get("days"):
            lines.append(f"| {lane} | 0 | — | — | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| **{lane}** | {s['days']} | {s['total_items']} | {s['total_in_pool']} "
            f"| {s['in_pool_rate']:.1%} | {s['total_fabricated']} | {s['fabrication_rate']:.1%} "
            f"| {s['hard_pad_days']}/{s['days']} ({s['hard_pad_day_rate']:.0%}) "
            f"| {s['padded_to_three_days']} | ${s['total_cost_usd']:.3f} |"
        )
    lines.extend(["", "## 逐日", ""])
    for lane in DEFAULT_LANES:
        s = summary.get(lane) or {}
        lines.append(f"### {lane}")
        if not s.get("daily"):
            lines.append("_无生产 trace_")
            lines.append("")
            continue
        for row in s["daily"]:
            fab = row.get("fabricated_syms") or []
            fab_s = ",".join(fab) if fab else "—"
            lines.append(
                f"- **{row['trade_date']}**: items={row['item_count']} in_pool={row['in_pool_count']} "
                f"硬凑={row['fabricated_count']} ({fab_s}) "
                f"{'⚠凑3' if row.get('padded_to_three') else ''} "
                f"${row.get('cost_usd') or 0:.3f}"
            )
        lines.append("")
    lines.extend(
        [
            "## 裁量参考",
            "- **in_pool_rate** 越低越好（pool 漏网）",
            "- **硬凑率** = 不在 near-miss 清单里的候选 / 总条数；**硬凑天数** = 当日有硬凑或凑满3条",
            "- 跑满 5+ 交易日再裁留；稀疏日 Opus 硬凑风险更高",
            "",
            "## Cut 条件（云端 CC 随时可停）",
            "- 本地 Grid/Aster 主链路 **不依赖** offpool，停 CC 不影响 scan/compile/store",
            "- **建议 cut** 若：硬凑天数 > 对手 lane、in_pool 持续 > 0、或 weekly 费用 > $0.50 且候选质量无增量",
            "- **建议留** 若：唯一发现有效 off-pool near-miss 且 0 硬凑/0 漏网",
            "- Cut 操作：停 `com.demo.aether.offpool` LaunchAgent 即可；Aether 页场外区变空，其余不变",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Off-pool A/B weekly report")
    ap.add_argument("--days", type=int, default=7, help="Lookback window (default 7)")
    ap.add_argument("--until", help="End date YYYY-MM-DD (default today EST)")
    ap.add_argument("--json", action="store_true", help="Print JSON only")
    args = ap.parse_args()

    until = dt.date.fromisoformat(args.until) if args.until else dt.datetime.now(EST).date()
    since = until - dt.timedelta(days=max(args.days - 1, 0))

    summary: dict[str, dict] = {}
    for lane in DEFAULT_LANES:
        traces = load_lane_traces(lane, since=since, until=until)
        summary[lane] = aggregate_lane_week(traces)

    payload = {
        "generated_at": dt.datetime.now(EST).isoformat(),
        "since": since.isoformat(),
        "until": until.isoformat(),
        "lanes": summary,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = until.isoformat()
    json_path = REPORT_DIR / f"ab_report_{since.isoformat()}_{stamp}.json"
    md_path = REPORT_DIR / f"ab_report_{since.isoformat()}_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(format_report(summary, since=since, until=until), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_report(summary, since=since, until=until))
        print(f"\nWrote {md_path}\nWrote {json_path}")


if __name__ == "__main__":
    main()
