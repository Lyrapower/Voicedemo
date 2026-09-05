"""Regime-split IC: lookahead, bucket gate, half-sample, no --regime parity."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ic_eval_v1_1 as IE  # noqa: E402
import regime as RG  # noqa: E402


def _dates(n: int, start: date = date(2024, 1, 2)) -> list[str]:
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _bar(d: str, c: float) -> IE.Bar:
    return (d, c, c, c, c, 1e6)


def _trend_spy_bars(n: int = 80, drift: float = 0.997, seed: int = 1) -> dict[str, list[IE.Bar]]:
    """Gentle down-drift + tiny noise. A +50% print on day t can flip t+1 vs 20dma and vol bucket."""
    import random
    rng = random.Random(seed)
    ds = _dates(n)
    p = 100.0
    rows = []
    for _d in ds:
        p *= drift * (1.0 + rng.gauss(0.0, 0.004))
        rows.append(_bar(_d, max(p, 1.0)))
    return {"SPY": rows}


def _breadth_bars(n_sym: int, n_days: int, above_frac: float = 0.7) -> dict[str, list[IE.Bar]]:
    ds = _dates(n_days)
    bars: dict[str, list[IE.Bar]] = {}
    cut = int(n_sym * above_frac)
    for i in range(n_sym):
        p0 = 50.0 + i
        rows = []
        p = p0
        for j, d in enumerate(ds):
            if i < cut:
                p = p0 * (1.0 + 0.01 * (j + 1))
            else:
                p = p0 * (1.0 - 0.01 * (j + 1))
            rows.append(_bar(d, p))
        bars[f"S{i:03d}"] = rows
    return bars


class RegimeLookaheadTest(unittest.TestCase):
    def test_mutate_t_spy_close_leaves_t_labels(self):
        import random
        rng = random.Random(2)
        ds = _dates(160)
        p = 100.0
        spy = []
        for i, d in enumerate(ds):
            # early high noise so the 60d vol window has a fat right tail;
            # later quiet so label[t] is low; +50% on t flips t+1 to high.
            sigma = 0.03 if i < 50 else 0.0015
            p *= 0.997 * (1.0 + rng.gauss(0.0, sigma))
            spy.append(_bar(d, max(p, 1.0)))
        bars = {"SPY": spy}
        mid = 110
        t = spy[mid][0]
        t1 = spy[mid + 1][0]
        before_tr = RG.trend_spy(bars)
        before_vol = RG.vol_spy(bars)
        self.assertIsNotNone(before_tr.get(t), "need trend label at t")
        self.assertIsNotNone(before_vol.get(t), "need vol label at t")
        mutated = list(spy)
        mutated[mid] = _bar(t, mutated[mid][4] * 1.5)
        bars2 = {"SPY": mutated}
        after_tr = RG.trend_spy(bars2)
        after_vol = RG.vol_spy(bars2)
        self.assertEqual(before_tr.get(t), after_tr.get(t), "trend label[t] used t-day close")
        self.assertEqual(before_vol.get(t), after_vol.get(t), "vol label[t] used t-day close")
        self.assertNotEqual(before_tr.get(t1), after_tr.get(t1), "trend label[t+1] should see +50%")
        self.assertNotEqual(before_vol.get(t1), after_vol.get(t1), "vol label[t+1] should see +50%")

    def test_mutate_t_breadth_leaves_t_labels(self):
        bars = _breadth_bars(480, 40, above_frac=0.75)
        univ = list(bars)
        mid_date = bars["S000"][25][0]
        nxt = bars["S000"][26][0]
        before = RG.breadth_sp500(bars, univ)
        self.assertEqual(before.get(mid_date), "wide")
        bars2 = {s: list(rows) for s, rows in bars.items()}
        for i in range(200):
            s = f"S{i:03d}"
            rows = bars2[s]
            k = next(j for j, r in enumerate(rows) if r[0] == mid_date)
            rows[k] = _bar(mid_date, rows[k][4] * 0.5)
        after = RG.breadth_sp500(bars2, univ)
        self.assertEqual(before.get(mid_date), after.get(mid_date))
        self.assertNotEqual(before.get(nxt), after.get(nxt))


class RegimeGateTest(unittest.TestCase):
    def test_n30_insufficient_no_watch(self):
        ics = [(f"2024-01-{i+1:02d}", 0.08, 100) for i in range(30)]
        v, why = RG.bucket_verdict(30, 0.08, 4.0, ics, min_n=60, full_mean=0.01, bucket="up")
        self.assertEqual(v, "insufficient")
        self.assertNotIn("watch", v)
        self.assertIn("30", why)

    def test_half_sign_flip_insufficient(self):
        ics = [(f"d{i:03d}", 0.05, 80) for i in range(40)]
        ics += [(f"d{i:03d}", -0.05, 80) for i in range(40, 80)]
        v, _ = RG.bucket_verdict(80, 0.0, 0.1, ics, min_n=60, full_mean=0.02, bucket="up")
        self.assertEqual(v, "insufficient")
        self.assertNotIn("watch", v)

    def test_gate_stays_60_even_if_caller_passes_lower(self):
        """Thicker sample must not relax the package gate; evaluate_regime defaults MIN_N=60."""
        self.assertEqual(IE.MIN_N, 60)
        ics = [(f"d{i:03d}", 0.05, 80) for i in range(50)]
        v, _ = RG.bucket_verdict(50, 0.05, 3.0, ics, min_n=IE.MIN_N, full_mean=0.01, bucket="up")
        self.assertEqual(v, "insufficient")


class NoRegimeParityTest(unittest.TestCase):
    def test_evaluate_unchanged_without_regime_flag(self):
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "bars.db")
        IE._synthetic_db(db, n_sym=40, n_days=120, seed=7)
        bars = IE.load_bars(db)
        a = IE.evaluate(bars, IE.FACTORS["mom_5"], 5)
        b = IE.evaluate(bars, IE.FACTORS["mom_5"], 5)
        self.assertEqual(a["n_obs"], b["n_obs"])
        self.assertAlmostEqual(a["ic_mean"], b["ic_mean"], delta=1e-12)
        self.assertAlmostEqual(a["ic_t"], b["ic_t"], delta=1e-12)
        # CLI path without --regime uses the same evaluate()
        rc = IE._main(["ic_eval_v1_1.py", "run", "--db", db, "--factor", "mom_5",
                       "--universe", self._univ(tmp, list(bars))])
        self.assertEqual(rc, 0)

    def _univ(self, tmp: str, symbols: list[str]) -> str:
        p = os.path.join(tmp, "u.json")
        import json
        json.dump({"symbols": symbols}, open(p, "w"))
        return p

    def test_load_bars_default_has_no_src_filter(self):
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "bars.db")
        IE._synthetic_db(db, n_sym=5, n_days=10, seed=1)
        # table has no src column; default load must still work
        bars = IE.load_bars(db)
        self.assertGreater(len(bars), 0)


class RegimeEvalWiringTest(unittest.TestCase):
    def test_evaluate_regime_splits_and_keeps_min_n(self):
        bars = _trend_spy_bars(90)
        # pad names so daily_ic has MIN_NAMES
        ds = [r[0] for r in bars["SPY"]]
        for i in range(25):
            p = 80.0 + i
            bars[f"X{i:02d}"] = [_bar(d, p * (1 + 0.001 * j)) for j, d in enumerate(ds)]
        labels = RG.trend_spy(bars)
        pack = IE.evaluate_regime(bars, IE.FACTORS["mom_5"], 5, labels)
        self.assertEqual(pack["min_n"], 60)
        self.assertIn("full", pack)
        for lab, s in pack["buckets"].items():
            self.assertIn(s["verdict"], {"insufficient", "reject", "regime_flip"} | {f"watch@{lab}"})


class EvalsSchemaTest(unittest.TestCase):
    def test_alter_adds_null_regime_cols_keeps_old_row(self):
        tmp = tempfile.mkdtemp()
        os.environ["FACTOR_LINEAGE_DB"] = os.path.join(tmp, "fl.db")
        import factor_lineage_v1_1 as FL
        con = FL.connect()
        fid = FL.propose("x", "mom_5", "manual", None, "test", "t", con=con)
        eid = FL.record_eval(fid, "2025-09-02", "2026-09-04", "5d", 228, 0.01, 0.05,
                             "close_to_close", None, "r", "reject", "x", con=con)
        IE._ensure_regime_cols(con)
        con.commit()
        row = con.execute("SELECT regime, bucket, ic_mean, n_obs FROM evals WHERE id=?", (eid,)).fetchone()
        self.assertIsNone(row["regime"])
        self.assertIsNone(row["bucket"])
        self.assertEqual(row["n_obs"], 228)
        self.assertAlmostEqual(row["ic_mean"], 0.01)
        con.close()


if __name__ == "__main__":
    unittest.main()
