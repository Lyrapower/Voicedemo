"""
Aether Nexus R5.4.x filter patch
--------------------------------
Drop-in modules for the four tasks in CURSOR_INSTRUCTIONS.md.

Design rules honored:
- logging-first: RejectionLogger has zero effect on filter behavior
- config over hardcode: all thresholds via FilterConfig
- dry-run guarantee: nothing here touches order execution
- sidecar is report-only and shares no state with the signal funnel
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional


@dataclass
class Candidate:
    symbol: str
    strike: float
    expiry: str
    dte: int
    spot: float
    delta: float
    gamma: float
    theta: float
    iv: float
    bid: float
    ask: float
    volume: int
    open_interest: int
    quote_source: str
    score: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float:
        m = self.mid
        return (self.ask - self.bid) / m if m > 0 else float("inf")


GREEK_KILL_RULES = frozenset({"delta", "gamma", "theta_ratio", "iv", "spread", "stale_quote"})


@dataclass
class PolicyV2Config:
    """Shadow policy — logging only until 3-day review activates thresholds."""

    theta_ratio_band: float = 0.03
    indicative_greek_soft: bool = True


def policy_v2_shadow(
    reasons: list[str],
    opt: dict,
    quote_source: str,
    theta_cap: float,
    cfg: PolicyV2Config,
) -> dict:
    """Counterfactual v2 pass/kill. Does not change live filtering."""
    v2_flags: list[str] = []
    v2_remaining: list[str] = []
    for reason in reasons:
        key = reason.split("=")[0]
        if cfg.indicative_greek_soft and quote_source == "indicative" and key in GREEK_KILL_RULES:
            v2_flags.append(f"indicative_soft:{key}")
            continue
        if key == "theta_ratio":
            tr = float(opt.get("theta_ratio", 0))
            if tr > theta_cap and tr <= theta_cap + cfg.theta_ratio_band:
                v2_flags.append(
                    f"theta_ratio_band:{tr:.4f} within +{cfg.theta_ratio_band} of cap {theta_cap:.4f}"
                )
                continue
        v2_remaining.append(reason)
    return {
        "v2_flags": v2_flags,
        "v2_would_kill": bool(v2_remaining),
        "v2_rescued": bool(reasons) and not bool(v2_remaining),
        "v2_remaining_reasons": v2_remaining,
    }


class PolicyV2Audit:
    """Aggregate shadow stats for one scan; append to Telegram digest."""

    def __init__(self, cfg: Optional[PolicyV2Config] = None):
        self.cfg = cfg or PolicyV2Config()
        self.hard_killed = 0
        self.v2_would_kill = 0
        self.v2_rescued = 0
        self.rescued_by_rule: dict[str, int] = {}
        self.v2_flag_counts: dict[str, int] = {}

    def observe(self, reasons: list[str], shadow: dict) -> None:
        if not reasons:
            return
        self.hard_killed += 1
        if shadow["v2_would_kill"]:
            self.v2_would_kill += 1
        if shadow["v2_rescued"]:
            self.v2_rescued += 1
            for r in reasons:
                key = r.split("=")[0]
                self.rescued_by_rule[key] = self.rescued_by_rule.get(key, 0) + 1
        for flag in shadow.get("v2_flags", []):
            prefix = flag.split(":")[0]
            self.v2_flag_counts[prefix] = self.v2_flag_counts.get(prefix, 0) + 1

    def digest_text(self) -> str:
        if not self.hard_killed:
            return ""
        drop = self.hard_killed - self.v2_would_kill
        pct = (drop / self.hard_killed * 100) if self.hard_killed else 0
        lines = [
            "— Policy V2 影子审计 (未改判定) —",
            f" 硬杀合约数: {self.hard_killed} → V2影子: {self.v2_would_kill}"
            f" (少杀 {drop}, -{pct:.1f}%)",
            f" V2可救回: {self.v2_rescued}",
        ]
        if self.rescued_by_rule:
            top = sorted(self.rescued_by_rule.items(), key=lambda kv: -kv[1])[:6]
            lines.append(" 救回主因: " + ", ".join(f"{k}={v}" for k, v in top))
        if self.v2_flag_counts:
            lines.append(
                " V2标记: "
                + ", ".join(f"{k}={v}" for k, v in sorted(self.v2_flag_counts.items(), key=lambda kv: -kv[1]))
            )
        return "\n".join(lines)


class RejectionLogger:
    """JSONL logger for every filtered-out candidate. No side effects on filtering."""

    def __init__(self, log_dir: str = "logs/rejections", scan_id: Optional[str] = None):
        self.scan_id = scan_id or time.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:6]
        date = time.strftime("%Y-%m-%d")
        self.path = Path(log_dir) / f"{date}_{self.scan_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self.kill_counts: dict[str, int] = {}
        self.near_misses: list[dict] = []

    def log(
        self,
        cand: Candidate,
        kill_rule: str,
        kill_value: float,
        threshold: float,
        extra: Optional[dict] = None,
    ) -> None:
        row = {
            "ts": time.time(),
            "scan_id": self.scan_id,
            "kill_rule": kill_rule,
            "kill_value": kill_value,
            "threshold_at_kill": threshold,
            **asdict(cand),
            "spread_pct": round(cand.spread_pct, 6),
        }
        if extra:
            row.update(extra)
        self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.kill_counts[kill_rule] = self.kill_counts.get(kill_rule, 0) + 1
        self.near_misses.append(row)

    def _aggregate_near_misses(self) -> list[dict]:
        """One tombstone per (sym, contract, score) — merge kill rules on same evaluation."""
        buckets: dict[tuple, dict] = {}
        for r in self.near_misses:
            key = (
                r.get("symbol"),
                r.get("strike"),
                r.get("expiry"),
                round(float(r.get("score") or 0), 2),
            )
            rule = str(r.get("kill_rule") or "")
            detail = (
                f"{rule} {float(r.get('kill_value', 0)):.4g}"
                f"→{float(r.get('threshold_at_kill', 0)):.4g}"
            )
            if key not in buckets:
                buckets[key] = {
                    "symbol": key[0],
                    "strike": key[1],
                    "expiry": key[2],
                    "score": key[3],
                    "quote_source": r.get("quote_source"),
                    "scan_id": r.get("scan_id") or self.scan_id,
                    "_rules": [rule] if rule else [],
                    "_details": [detail] if rule else [],
                }
            else:
                b = buckets[key]
                if rule and rule not in b["_rules"]:
                    b["_rules"].append(rule)
                    b["_details"].append(detail)
        out: list[dict] = []
        for b in buckets.values():
            rules = b.pop("_rules", [])
            details = b.pop("_details", [])
            b["kill_rule"] = "+".join(rules) if rules else "unknown"
            b["kill_summary"] = " · ".join(details)
            out.append(b)
        return sorted(out, key=lambda x: float(x.get("score") or 0), reverse=True)

    def summary(self, top_n: int = 10) -> dict:
        aggregated = self._aggregate_near_misses()
        near = aggregated[:top_n]
        return {
            "scan_id": self.scan_id,
            "kill_counts": dict(sorted(self.kill_counts.items(), key=lambda kv: -kv[1])),
            "near_miss_top": [
                {
                    k: r[k]
                    for k in (
                        "symbol",
                        "strike",
                        "expiry",
                        "score",
                        "kill_rule",
                        "kill_summary",
                        "quote_source",
                        "scan_id",
                    )
                    if k in r
                }
                for r in near
            ],
        }

    def digest_text(self) -> str:
        s = self.summary()
        lines = ["过滤原因分布:"]
        lines += [f" {rule}: {n}" for rule, n in s["kill_counts"].items()]
        lines.append("— 高分被杀 Top —")
        for r in s["near_miss_top"]:
            summary = r.get("kill_summary") or (
                f"{r.get('kill_rule')} ({r.get('kill_value')} vs {r.get('threshold_at_kill')})"
            )
            lines.append(
                f" {r['symbol']} score={r['score']:.1f} killed_by={r['kill_rule']}"
                f" ({summary}, {r.get('quote_source', '')})"
            )
        return "\n".join(lines)

    def close(self) -> None:
        self._fh.close()


@dataclass
class FilterConfig:
    max_spread_pct: float = 0.08
    min_vol_fallback: int = 50
    min_oi_fallback: int = 500
    iv_keep_pct: float = 70.0
    delta_band_pct: tuple = (20.0, 80.0)
    iv_hard_max: float = 3.0


def liquidity_ok(cand: Candidate, cfg: FilterConfig, logger: Optional[RejectionLogger] = None) -> bool:
    if cand.quote_source == "indicative":
        ok = cand.volume >= cfg.min_vol_fallback or cand.open_interest >= cfg.min_oi_fallback
        if not ok and logger:
            logger.log(
                cand,
                "liquidity_vol_oi_fallback",
                float(max(cand.volume, cand.open_interest)),
                float(cfg.min_oi_fallback),
                extra={"liquidity_path": "vol_oi_fallback"},
            )
        return ok

    ok = cand.spread_pct <= cfg.max_spread_pct
    if not ok and logger:
        logger.log(
            cand,
            "spread",
            cand.spread_pct,
            cfg.max_spread_pct,
            extra={"liquidity_path": "spread"},
        )
    return ok


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("inf")
    xs = sorted(values)
    k = (len(xs) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    frac = k - lo
    return xs[lo] * (1 - frac) + xs[hi] * frac


class PercentileCaps:
    def __init__(self, universe: Iterable[Candidate], cfg: FilterConfig):
        cands = list(universe)
        self.cfg = cfg
        self.iv_cap = min(_percentile([c.iv for c in cands], cfg.iv_keep_pct), cfg.iv_hard_max)
        lo_p, hi_p = cfg.delta_band_pct
        deltas = [c.delta for c in cands]
        self.delta_lo = _percentile(deltas, lo_p)
        self.delta_hi = _percentile(deltas, hi_p)

    def iv_ok(self, cand: Candidate, logger: Optional[RejectionLogger] = None) -> bool:
        ok = cand.iv <= self.iv_cap
        if not ok and logger:
            logger.log(cand, "iv_pctile", cand.iv, self.iv_cap)
        return ok

    def delta_ok(self, cand: Candidate, logger: Optional[RejectionLogger] = None) -> bool:
        ok = self.delta_lo <= cand.delta <= self.delta_hi
        if not ok and logger:
            thr = self.delta_lo if cand.delta < self.delta_lo else self.delta_hi
            logger.log(cand, "delta_pctile", cand.delta, thr)
        return ok

    def thresholds(self) -> dict:
        return {
            "iv_cap_today": round(self.iv_cap, 4),
            "delta_band_today": (round(self.delta_lo, 4), round(self.delta_hi, 4)),
        }


def hotlist_report(mover_candidates: Iterable[Candidate], score_fn, min_score: float = 35.0) -> str:
    lines = ["场外观察 (report-only, 不产生信号):"]
    scored = sorted(((score_fn(c), c) for c in mover_candidates), key=lambda t: -t[0])
    hits = [(s, c) for s, c in scored if s >= min_score]
    if not hits:
        lines.append(" 无 score>=%.0f 的场外候选" % min_score)
    for s, c in hits[:5]:
        lines.append(
            f" {c.symbol} score={s:.1f} ${c.spot} "
            f"{c.strike} {c.expiry} ({c.dte}d) Δ={c.delta:.3f}"
        )
    return "\n".join(lines)
