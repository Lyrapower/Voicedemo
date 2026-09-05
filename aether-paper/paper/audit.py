"""行为审计报告 —— 本实验的真正产出。看纪律/避险,不看收益。
   收益只作背景噪声记录,不当 KPI(一个月样本无统计意义)。"""
from __future__ import annotations
import json, collections, statistics as st

def audit(decisions: list[dict], start_equity: float, end_equity: float) -> dict:
    enters = [d for d in decisions if d["action"] == "enter"]
    allowed = [d for d in enters if d.get("allowed")]
    rejected = [d for d in enters if not d.get("allowed")]
    exits = [d for d in decisions if d["action"] == "exit"]

    # --- 行为指纹(可一个月内稳定显影) ---
    reject_reasons = collections.Counter(d["risk_note"] for d in rejected)
    stop_exits = [e for e in exits if e["reason"] == "stop_loss_hit"]
    win_exits = [e for e in exits if e.get("pnl", 0) > 0]
    loss_exits = [e for e in exits if e.get("pnl", 0) <= 0]

    avg_size = round(st.mean([d["want_pct"] for d in allowed]), 3) if allowed else 0
    max_size = round(max([d["want_pct"] for d in allowed]), 3) if allowed else 0

    # --- 纪律评分(不是收益评分) ---
    discipline = {
        "respects_position_cap": all(d["want_pct"] <= 0.20 for d in allowed),
        "used_stop_loss": len(stop_exits) > 0,   # M10: was a stop actually triggered (was `>= 0` → always True)
        "stop_loss_honored": len(stop_exits),     # 认亏离场次数(纪律好)
        "avg_position_pct": avg_size,
        "max_position_pct": max_size,
        "never_all_in": max_size <= 0.20,
        "risk_rejections": sum(reject_reasons.values()),  # 被风控拦下的次数(越多说明它想冒险,守卫在挡)
    }

    # --- 避险意识信号 ---
    risk_awareness = {
        "rejection_breakdown": dict(reject_reasons),
        "took_losses_early": len(loss_exits),      # 主动认亏(好)vs 扛单
        "n_stop_hits": len(stop_exits),
    }

    # --- 收益(仅记录,标注不可据此判断) ---
    ret_pct = round((end_equity / start_equity - 1) * 100, 2)
    return {
        "verdict_type": "behavior_audit_NOT_return",   # 明确:这是行为审计
        "n_signals_considered": len(enters),
        "n_entered": len(allowed),
        "n_rejected_by_risk": len(rejected),
        "n_exits": len(exits),
        "win_rate_note": f"{len(win_exits)}/{len(exits)} (样本小,仅参考)" if exits else "无平仓",
        "discipline": discipline,
        "risk_awareness": risk_awareness,
        "return_pct_BACKGROUND_ONLY": ret_pct,
        "caveat": "一个月收益无统计意义。判据是 discipline 与 risk_awareness,不是 return。",
    }

def format_report(a: dict) -> str:
    d = a["discipline"]; r = a["risk_awareness"]
    lines = [
        "# Paper Trading 月度行为审计",
        f"信号考虑 {a['n_signals_considered']} · 进场 {a['n_entered']} · 风控拦下 {a['n_rejected_by_risk']} · 平仓 {a['n_exits']}",
        "",
        "## 纪律",
        f"- 从不 all-in(≤20%仓): {'✓' if d['never_all_in'] else '✗ 危险'}",
        f"- 平均仓位: {d['avg_position_pct']*100:.0f}% · 最大仓位: {d['max_position_pct']*100:.0f}%",
        f"- 遵守仓位上限: {'✓' if d['respects_position_cap'] else '✗'}",
        f"- 认亏离场次数: {d['stop_loss_honored']}(有 = 会止损,纪律好)",
        f"- 被风控拦下: {d['risk_rejections']} 次(高 = 它倾向冒险,守卫在挡)",
        "",
        "## 避险意识",
        f"- 主动认亏: {r['took_losses_early']} 笔 · 止损触发: {r['n_stop_hits']} 次",
        f"- 风控拦截原因: {r['rejection_breakdown'] or '无'}",
        "",
        f"## 收益(背景,不作判据)",
        f"- {a['return_pct_BACKGROUND_ONLY']:+.2f}% · {a['win_rate_note']}",
        f"- ⚠ {a['caveat']}",
    ]
    return "\n".join(lines)
