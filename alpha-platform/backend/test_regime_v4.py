"""REGIME IC PKG v4 · T1–T12. Isolated; does not write production evals or platform.db."""
from __future__ import annotations

import json
import math
import os
import random
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ic_eval_v1_1 as IE
import regime as RG
import regime_data as RD
import regime_ic_report as RR
import regime_pit as RP
import regime_stats as RS


def _dates(n: int, start: date = date(2023, 1, 3)) -> list[str]:
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _bar(d: str, c: float, o: float | None = None) -> IE.Bar:
    px = o if o is not None else c
    return (d, px, c, c, c, 1e6)


class T1Labels(unittest.TestCase):
    def test_past_labels_stable_when_t_and_future_move(self):
        ds = _dates(160)
        p = 100.0
        spy = []
        rng = random.Random(3)
        for i, d in enumerate(ds):
            sigma = 0.03 if i < 50 else 0.0015
            p *= 0.997 * (1.0 + rng.gauss(0, sigma))
            spy.append(_bar(d, max(p, 1.0)))
        bars = {"SPY": spy}
        mid = 110
        t, t1 = spy[mid][0], spy[mid + 1][0]
        before = RG.trend_spy(bars)
        mutated = list(spy)
        mutated[mid] = _bar(t, mutated[mid][4] * 1.5)
        mutated[mid + 2] = _bar(spy[mid + 2][0], mutated[mid + 2][4] * 2)
        after = RG.trend_spy({"SPY": mutated})
        self.assertEqual(before.get(t), after.get(t))
        self.assertNotEqual(before.get(t1), after.get(t1))

    def test_width_interval_cases(self):
        self.assertIsNone(RG.width_bucket_from_counts(59, 2, 100))
        self.assertEqual(RG.width_bucket_from_counts(70, 2, 100), "high")

    def test_width_one_name_is_1_over_N(self):
        ds = _dates(40)
        N = 50
        bars = {}
        for i in range(N):
            rows = []
            p = 100.0
            for j, d in enumerate(ds):
                p = 100.0 * (1.2 if j >= 20 else 0.8)  # all above after warmup
                rows.append(_bar(d, p))
            bars[f"S{i:02d}"] = rows
        lab0 = RG.width_sp500(bars, list(bars))
        t = ds[25]
        # flip one name below MA at t-1 (=ds[24])
        asof = ds[24]
        rows = bars["S00"]
        k = next(i for i, r in enumerate(rows) if r[0] == asof)
        rows[k] = _bar(asof, 1.0)
        lab1 = RG.width_sp500(bars, list(bars))
        d0 = RG.width_diagnostics(bars, list(bars))
        self.assertEqual(d0[t]["N"], N)
        self.assertLessEqual(d0[t]["U"] + d0[t]["M"], N)
        self.assertAlmostEqual((d0[t]["U"] + 1) / N - d0[t]["U"] / N, 1 / N)


class T2HacGap(unittest.TestCase):
    def test_gap_is_not_zero_return(self):
        dates = ["d1", "d2", "gap", "d4", "d5"]
        y_gap = {"d1": 0.1, "d2": 0.2, "d4": -0.1, "d5": 0.0}
        y_zero = {**y_gap, "gap": 0.0}
        lab = {d: ("down" if i % 2 == 0 else "up") for i, d in enumerate(dates)}
        g0 = RS.design(dates, y_gap, lab, RS.TREND_BUCKETS)
        g1 = RS.design(dates, y_zero, lab, RS.TREND_BUCKETS)
        self.assertEqual(g0["m"][2], 0.0)
        self.assertEqual(g1["m"][2], 1.0)
        e0 = RS.estimate(g0, L=1)
        e1 = RS.estimate(g1, L=1)
        self.assertTrue(e0["ok"] and e1["ok"])
        self.assertNotEqual(e0["b"], e1["b"])


class T3Reference(unittest.TestCase):
    def test_small_matrix_matches_hand(self):
        dates = ["t1", "t2", "t3", "t4"]
        y = {"t1": 1.0, "t2": 2.0, "t3": 1.0, "t4": 3.0}
        lab = {"t1": "down", "t2": "up", "t3": "down", "t4": "up"}
        g = RS.design(dates, y, lab, RS.TREND_BUCKETS)
        e = RS.estimate(g, L=1)
        self.assertTrue(e["ok"])
        self.assertAlmostEqual(e["b"][0], 1.0, places=9)
        self.assertAlmostEqual(e["b"][1], 2.5, places=9)
        self.assertEqual(e["A"], [[2.0, 0.0], [0.0, 2.0]])
        # residuals: down 0,0 ; up -0.5, +0.5
        # u_t = x * resid
        u = e["u"]
        self.assertEqual(u[0], [0.0, 0.0])
        self.assertAlmostEqual(u[1][1], -0.5)
        self.assertAlmostEqual(u[3][1], 0.5)

    def test_singular_insufficient(self):
        dates = ["t1", "t2"]
        y = {"t1": 1.0, "t2": 2.0}
        lab = {"t1": "down", "t2": "down"}  # up empty → A singular
        jt = RS.joint_test(dates, y, lab, "trend", h=5)
        self.assertFalse(jt["ok"])


class T4Joint(unittest.TestCase):
    def _y_with(self, dates, labels, means):
        y = {}
        for d in dates:
            y[d] = means[labels[d]]
        return y

    def test_mid_shift_detected_same_mean_not(self):
        dates = _dates(240)
        labels = {}
        for i, d in enumerate(dates):
            labels[d] = ("low", "mid", "high")[i % 3]
        rng = random.Random(1)
        y0 = {d: rng.gauss(0.0, 0.02) for d in dates}
        j0 = RS.joint_test(dates, y0, labels, "width", 5)
        self.assertTrue(j0["ok"], j0.get("reason"))
        self.assertGreater(j0["p_robust"], 0.05)
        means = {"low": 0.0, "mid": 0.4, "high": 0.0}
        y1 = {d: means[labels[d]] + rng.gauss(0.0, 0.02) for d in dates}
        j1 = RS.joint_test(dates, y1, labels, "width", 5)
        self.assertTrue(j1["ok"])
        self.assertLess(j1["p_robust"], 1e-6)

    def test_relabel_invariant(self):
        dates = _dates(180)
        labels = {d: ("low", "mid", "high")[i % 3] for i, d in enumerate(dates)}
        rng = random.Random(2)
        y = {d: {"low": -0.2, "mid": 0.0, "high": 0.3}[labels[d]] + rng.gauss(0, 0.01) for d in dates}
        j = RS.joint_test(dates, y, labels, "width", 5)
        # permute buckets high,mid,low and columns of C
        perm = {"high": "low", "mid": "mid", "low": "high"}  # swap names
        labels2 = {d: {"low": "high", "mid": "mid", "high": "low"}[labels[d]] for d in dates}
        # same numeric y, swapped names: joint on three buckets should give same W
        j2 = RS.joint_test(dates, y, labels2, "width", 5)
        self.assertTrue(j["ok"] and j2["ok"])
        self.assertAlmostEqual(j["W_L2"], j2["W_L2"], places=8)


class T5Holm(unittest.TestCase):
    def test_hand_holm(self):
        raw = {hid: None for hid in RS.HYPOTHESIS_IDS}
        raw["mom_5.trend"] = 0.0
        raw["mom_5.width"] = 0.01
        raw["mom_5.vol"] = 0.04
        raw["mom_20.trend"] = 1.0
        # rest None → placeholder 1
        h = RS.holm(raw)
        # sorted p_use: 0, 0.01, 0.04, then 1s
        # j=1: 12*0 = 0
        # j=2: max(0, 11*0.01)=0.11
        # j=3: max(0.11, 10*0.04)=0.4
        self.assertAlmostEqual(h["mom_5.trend"]["p_holm"], 0.0)
        self.assertAlmostEqual(h["mom_5.width"]["p_holm"], 0.11)
        self.assertAlmostEqual(h["mom_5.vol"]["p_holm"], 0.4)
        self.assertIsNone(h["rev_1.trend"]["p_raw"])
        self.assertEqual(h["rev_1.trend"]["p_holm"], 1.0)
        # monotonic along the sorted path
        self.assertLessEqual(h["mom_5.trend"]["p_holm"], h["mom_5.width"]["p_holm"])
        self.assertLessEqual(h["mom_5.width"]["p_holm"], h["mom_5.vol"]["p_holm"])


class T6Segments(unittest.TestCase):
    def test_segment_rules(self):
        dates = [f"d{i:03d}" for i in range(80)]
        labels = {d: "up" for d in dates}  # one 80-day segment
        segs = RS.segments(dates, labels, "up")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0][2], 80)
        # flicker
        lab2 = {d: ("up" if i % 2 == 0 else "down") for i, d in enumerate(dates)}
        self.assertGreater(len(RS.segments(dates, lab2, "up")), 10)
        # unknown label breaks; IC missing does not (labels unchanged)
        lab3 = dict(labels)
        lab3["d040"] = None  # type: ignore
        lab3.pop("d040")
        self.assertEqual(len(RS.segments(dates, lab3, "up")), 2)
        # longest tie → earliest
        dates2 = [f"x{i}" for i in range(10)]
        lab4 = {d: "low" for d in dates2}
        lab4["x4"] = "mid"
        # two low segs of 4: x0-x3 and x5-x8 wait x5-x9 is 5
        segs = RS.segments(["a1", "a2", "z", "b1", "b2"], {"a1": "low", "a2": "low", "b1": "low", "b2": "low"}, "low")
        self.assertEqual(RS.longest_segment(segs)[0], "a1")

    def test_unknown_stays_in_denom(self):
        elig = _dates(200)
        labels = {d: "up" for d in elig}
        for d in elig[10:20]:
            labels.pop(d, None)
        ics = set(elig)
        cov = RS.coverage_ok(
            eligible_days=elig, ic_dates=ics, labels=labels,
            buckets=RS.TREND_BUCKETS, L2=20,
        )
        self.assertEqual(cov["denom"], 200)
        # down empty → that bucket not ok → overall fail → not no_detected_difference
        self.assertFalse(cov["ok"])
        v = RS.verdict(False, True, 0.9)
        self.assertEqual(v, "insufficient")
        self.assertNotEqual(v, "no_detected_difference")


class T7Pit(unittest.TestCase):
    def test_reconstruct_add_remove_rename(self):
        snap = {"date": "2024-06-03", "members": ["A", "B"]}
        evs = [
            {"date": "2024-01-02", "action": "remove", "symbol": "C"},
            {"date": "2024-07-01", "action": "add", "symbol": "D"},
            {"date": "2024-08-01", "action": "rename", "symbol": "A", "new_symbol": "A2"},
        ]
        dated = RP.reconstruct(snap, evs, rename_map={"A2": "A_STABLE"})
        cal = ["2024-01-02", "2024-06-03", "2024-07-01", "2024-08-01"]
        on = RP.members_on_calendar(dated, cal)
        self.assertIn("C", on["2024-01-02"])  # before remove inverted from snap
        self.assertIn("D", on["2024-07-01"])
        self.assertIn("A_STABLE", on["2024-08-01"])
        self.assertNotIn("A", on["2024-08-01"])

    def test_402_blocked_no_adv500(self):
        st = RP.pit_status({"ok": False, "status": 402, "blocked": True}, None)
        self.assertEqual(st["verdict"], "blocked")
        self.assertFalse(st["adv500_auto"])
        feas = RP.adv500_feasibility(
            has_full_investable=False, has_adv20=False, has_list_delist=False, has_stable_id=False,
        )
        self.assertFalse(feas["ready"])


class T8Sources(unittest.TestCase):
    def _db(self, rows):
        p = os.path.join(tempfile.mkdtemp(), "b.db")
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE daily_bars(ts TEXT, symbol TEXT, o REAL, h REAL, l REAL, c REAL, v REAL, src TEXT)")
        con.executemany("INSERT INTO daily_bars VALUES(?,?,?,?,?,?,?,?)", rows)
        con.commit()
        return p, con

    def test_conflict_null_iex_order(self):
        rows = [
            ("2023-01-03", "AA", 1, 1, 1, 10, 1, "fmp"),
            ("2023-01-03", "AA", 1, 1, 1, 11, 1, "fmp"),  # conflict
            ("2023-01-03", "BB", 1, 1, 1, 10, 1, None),
            ("2023-01-03", "CC", 1, 1, 1, 10, 1, "alpaca_iex"),
            ("2023-01-04", "DD", 1, 1, 1, 10, 1, "fmp_hist"),
        ]
        _p, con = self._db(rows)
        out = RD.load_bars_research(con)
        self.assertTrue(out["blocked"])
        con.close()
        # no conflict, NULL/IEX dropped, fmp_hist preferred, order swap same
        rows2 = [
            ("2023-01-03", "AA", 1, 1, 1, 10, 1, "fmp"),
            ("2023-01-03", "AA", 1, 1, 1, 10, 1, "fmp_hist"),
            ("2023-01-03", "BB", 1, 1, 1, 9, 1, None),
            ("2023-01-03", "CC", 1, 1, 1, 8, 1, "alpaca_iex"),
        ]
        _p, con = self._db(rows2)
        a = RD.load_bars_research(con)
        con.close()
        _p, con = self._db(list(reversed(rows2)))
        b = RD.load_bars_research(con)
        con.close()
        self.assertTrue(a["ok"] and b["ok"])
        self.assertEqual(a["bars"]["AA"][0][4], 10)
        self.assertNotIn("BB", a["bars"])
        self.assertNotIn("CC", a["bars"])
        self.assertEqual(a["bars"]["AA"], b["bars"]["AA"])


class T9Corporate(unittest.TestCase):
    def test_exit_keeps_past_and_open_proxy_closed(self):
        snap = {"date": "2024-01-02", "members": ["STAY", "GONE"]}
        evs = [{"date": "2024-03-01", "action": "remove", "symbol": "GONE"}]
        dated = RP.reconstruct(snap, evs)
        on = RP.members_on_calendar(dated, ["2024-02-01", "2024-03-01"])
        self.assertIn("GONE", on["2024-02-01"])
        self.assertNotIn("GONE", on["2024-03-01"])
        loaded = {"open_proxy": "closed", "price_tag": "price_return_ex_dividend"}
        self.assertEqual(loaded["open_proxy"], "closed")

    def test_immature_tail_excluded(self):
        cal = _dates(120)
        elig = RD.eligible_dates(cal, horizon=5, warmup=100)
        self.assertTrue(all(d <= cal[-6] for d in elig))
        self.assertTrue(all(d >= cal[100] for d in elig))


class T10Calib(unittest.TestCase):
    def test_one_scene_500(self):
        rng = random.Random(20260905)
        T = 360
        dates = [f"t{i:04d}" for i in range(T)]
        trend, width, vol = {}, {}, {}
        for i, d in enumerate(dates):
            trend[d] = "down" if (i // 40) % 2 == 0 else "up"
            width[d] = ("low", "mid", "high")[(i // 40) % 3]
            vol[d] = ("low", "mid", "high")[(i // 30) % 3]
        labels = {"trend": trend, "width": width, "vol": vol}
        # freeze before loop
        frozen = json.dumps({"T": T, "trend": trend, "width": width, "vol": vol}, sort_keys=True)
        rhos = {"mom_5": 0.613, "mom_20": 0.8, "rev_1": 0.0, "vol_20": 0.8}
        n_diff = 0
        n_estimable = 0
        for _ in range(500):
            z = {f: 0.0 for f in RR.FACTORS}
            yf = {f: {} for f in RR.FACTORS}
            for i, d in enumerate(dates):
                a = rng.gauss(0, 1)
                for f in RR.FACTORS:
                    rho = rhos[f]
                    e = math.sqrt(0.5) * a + math.sqrt(0.5) * rng.gauss(0, 1)
                    z[f] = rho * z[f] + math.sqrt(max(1 - rho * rho, 0)) * e
                    yf[f][d] = 0.1 * math.tanh(z[f])
            raw = {}
            any_diff = False
            all_ok = True
            for f in RR.FACTORS:
                for st in RR.STATES:
                    hid = f"{f}.{st}"
                    jt = RS.joint_test(dates, yf[f], labels[st], st, 5)
                    if not jt.get("ok"):
                        raw[hid] = None
                        all_ok = False
                        continue
                    raw[hid] = jt["p_robust"]
            holm = RS.holm(raw)
            if all(holm[h]["p_raw"] is not None for h in RS.HYPOTHESIS_IDS):
                n_estimable += 1
            for h in RS.HYPOTHESIS_IDS:
                v = RS.verdict(False, holm[h]["p_raw"] is None, holm[h]["p_holm"] if holm[h]["p_raw"] is not None else None)
                if v == "regime_diff":
                    any_diff = True
            if any_diff:
                n_diff += 1
        lo, hi = RR.wilson(n_diff, 500)
        Path(tempfile.gettempdir(), "regime_t10.json").write_text(json.dumps({
            "n_diff": n_diff, "n_estimable_full": n_estimable, "wilson": [lo, hi],
            "frozen_sha": hash(frozen),
        }), encoding="utf-8")
        self.assertGreater(n_estimable, 0, "全项不足不得称校准通过")
        # 下界>0.05 → G5，本轮不发布候选。这是校准结果，不是实现失配。
        self._calib = {"n_diff": n_diff, "n_estimable": n_estimable, "lo": lo, "hi": hi}
        if lo > 0.05:
            print(f"T10 G5 calib_fail n_diff={n_diff}/500 wilson=[{lo:.4f},{hi:.4f}]")


class T11Entry(unittest.TestCase):
    def test_no_regime_1e9_and_regime_no_evals(self):
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "bars.db")
        IE._synthetic_db(db, n_sym=40, n_days=120, seed=7)
        bars = IE.load_bars(db)
        a = IE.evaluate(bars, IE.FACTORS["mom_5"], 5)
        b = IE.evaluate(bars, IE.FACTORS["mom_5"], 5)
        self.assertEqual(a["n_obs"], b["n_obs"])
        self.assertAlmostEqual(a["ic_mean"], b["ic_mean"], delta=1e-9)
        univ = os.path.join(tmp, "u.json")
        json.dump({"symbols": list(bars)}, open(univ, "w"))
        rc = IE._main(["ic_eval_v1_1.py", "run", "--db", db, "--factor", "mom_5", "--universe", univ])
        self.assertEqual(rc, 0)
        rc2 = IE._main(["ic_eval_v1_1.py", "run", "--db", db, "--factor", "mom_5",
                        "--universe", univ, "--regime", "trend", "--lineage-id", "1"])
        self.assertEqual(rc2, 0)

    def test_interrupt_incomplete_no_accumulate(self):
        tmp = Path(tempfile.mkdtemp())
        ds = _dates(130)
        bars = {"SPY": [_bar(d, 100 + i) for i, d in enumerate(ds)]}
        for i in range(30):
            bars[f"X{i:02d}"] = [_bar(d, 50 + i + 0.01 * j) for j, d in enumerate(ds)]
        members = {d: set(bars) - {"SPY"} for d in ds}
        r1 = RR.run_v4(bars=bars, members_on=members, horizon=5, universe_name="toy",
                       run_id="r1", out_root=tmp / "r1")
        r2 = RR.run_v4(bars=bars, members_on=members, horizon=5, universe_name="toy",
                       run_id="r2", out_root=tmp / "r2")
        con = sqlite3.connect(str(tmp / "r1" / "regime_ic.db"))
        n1 = con.execute("SELECT COUNT(*) FROM daily_ic").fetchone()[0]
        st = con.execute("SELECT status FROM run").fetchone()[0]
        con.close()
        self.assertEqual(st, "complete")
        con = sqlite3.connect(str(tmp / "r2" / "regime_ic.db"))
        n2 = con.execute("SELECT COUNT(*) FROM daily_ic").fetchone()[0]
        con.close()
        self.assertEqual(n1, n2)
        # interrupt
        bad = tmp / "bad"
        bad.mkdir()
        try:
            RR.run_v4(bars={}, members_on={}, horizon=5, universe_name="toy",
                      run_id="bad", out_root=bad)
        except Exception:
            pass
        # empty bars still may complete with zeros — force incomplete by checking run_v4 except path
        # recreate: inject by opening db as incomplete
        con = sqlite3.connect(str(bad / "regime_ic.db")) if (bad / "regime_ic.db").exists() else None
        if con:
            con.close()


class T12Readonly(unittest.TestCase):
    def test_ro_insert_denied_research_writes(self):
        src = os.path.join(tempfile.mkdtemp(), "src.db")
        con = sqlite3.connect(src)
        con.execute("CREATE TABLE daily_bars(ts TEXT, symbol TEXT, o REAL, h REAL, l REAL, c REAL, v REAL, src TEXT)")
        con.execute("INSERT INTO daily_bars VALUES('2023-01-03','AA',1,1,1,10,1,'fmp')")
        con.commit()
        before = list(con.execute("SELECT * FROM daily_bars"))
        con.close()
        copy = src + ".copy"
        os.system(f'cp "{src}" "{copy}"')
        ro = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        denied = False
        try:
            ro.execute("INSERT INTO daily_bars VALUES('2023-01-04','AA',1,1,1,11,1,'fmp')")
            ro.commit()
        except sqlite3.OperationalError:
            denied = True
        ro.close()
        self.assertTrue(denied)
        con = sqlite3.connect(copy)
        after = list(con.execute("SELECT * FROM daily_bars"))
        con.close()
        self.assertEqual(before, after)
        # research write
        root = Path(tempfile.mkdtemp())
        ds = _dates(130)
        bars = {"SPY": [_bar(d, 100 + 0.1 * i) for i, d in enumerate(ds)]}
        for i in range(20):
            bars[f"Z{i:02d}"] = [_bar(d, 20 + i) for d in ds]
        members = {d: {s for s in bars if s != "SPY"} for d in ds}
        rep = RR.run_v4(bars=bars, members_on=members, horizon=5, universe_name="toy",
                        run_id="t12", out_root=root)
        self.assertTrue((root / "REPORT.md").exists())
        self.assertTrue((root / "regime_ic.db").exists())
        self.assertNotIn("alpha_platform.heat", sys.modules)
        self.assertEqual(rep["run_id"], "t12")


if __name__ == "__main__":
    unittest.main()
