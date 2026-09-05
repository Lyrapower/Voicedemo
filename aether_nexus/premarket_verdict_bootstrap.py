"""S1 — bootstrap CI for A/B return differential (raw + adjusted)."""
from __future__ import annotations

import random
from typing import Any

from premarket_ab_clock import AB_LEDGER_START_DATE
from premarket_ab_pairing import VERDICT_WINDOW_DAYS, paired_daily_diffs, paired_scorable_dates


def bootstrap_ab_ci(
    *,
    adjusted: bool = False,
    n_samples: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    diffs = [d for _, d in paired_daily_diffs(adjusted=adjusted, for_verdict=True)]
    n_paired = len(paired_scorable_dates(limit=VERDICT_WINDOW_DAYS, for_verdict=True))
    if len(diffs) < 2:
        return {
            "board": "adjusted" if adjusted else "raw",
            "n_days": len(diffs),
            "n_paired_scorable": n_paired,
            "verdict_window_days": VERDICT_WINDOW_DAYS,
            "verdict_window_start": AB_LEDGER_START_DATE,
            "mean_diff_pct": None,
            "ci90_low": None,
            "ci90_high": None,
            "verdict": "INCONCLUSIVE",
            "reason": "insufficient_scorable_days",
        }
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_samples):
        sample = [rng.choice(diffs) for _ in range(len(diffs))]
        means.append(sum(sample) / len(sample))
    means.sort()
    lo = means[int(0.05 * len(means))]
    hi = means[int(0.95 * len(means))]
    mean = sum(diffs) / len(diffs)
    crosses_zero = lo <= 0 <= hi
    verdict = "INCONCLUSIVE" if crosses_zero else ("SONNET" if mean > 0 else "GRID")
    return {
        "board": "adjusted" if adjusted else "raw",
        "n_days": len(diffs),
        "n_paired_scorable": n_paired,
        "verdict_window_days": VERDICT_WINDOW_DAYS,
        "verdict_window_start": AB_LEDGER_START_DATE,
        "mean_diff_pct": round(mean * 100, 4),
        "ci90_low": round(lo * 100, 4),
        "ci90_high": round(hi * 100, 4),
        "verdict": verdict,
        "crosses_zero": crosses_zero,
        "bootstrap_n": n_samples,
        "resample_unit": "paired_day_diff",
    }


def dual_verdict_report() -> dict[str, Any]:
    return {
        "raw": bootstrap_ab_ci(adjusted=False),
        "adjusted": bootstrap_ab_ci(adjusted=True),
        "protocol": "bootstrap_10000_ci90_paired_void_symmetric",
        "verdict_window_days": VERDICT_WINDOW_DAYS,
        "verdict_window_start": AB_LEDGER_START_DATE,
        "inconclusive_triggers_extension": True,
    }
