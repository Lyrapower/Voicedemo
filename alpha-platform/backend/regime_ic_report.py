"""v4 regime IC research runner. Writes only research/regime_ic_v4/<run_id>/. Never writes evals."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ic_eval_v1_1 as IE  # noqa: E402
import regime as RG  # noqa: E402
import regime_data as RD  # noqa: E402
import regime_pit as RP  # noqa: E402
import regime_stats as RS  # noqa: E402

FACTORS = ("mom_5", "mom_20", "rev_1", "vol_20")
STATES = ("trend", "width", "vol")
REPO = Path(__file__).resolve().parents[2]
RESEARCH_ROOT = REPO / "research" / "regime_ic_v4"
SCHEMA = """
CREATE TABLE run (
  run_id TEXT PRIMARY KEY,
  status TEXT,
  started TEXT,
  finished TEXT,
  params TEXT
);
CREATE TABLE daily_ic (
  run_id TEXT, d TEXT, factor TEXT, ic REAL, n INTEGER,
  PRIMARY KEY (run_id, d, factor)
);
CREATE TABLE bucket_stats (
  run_id TEXT, hid TEXT, payload TEXT,
  PRIMARY KEY (run_id, hid)
);
CREATE TABLE hypothesis_results (
  run_id TEXT, hid TEXT, payload TEXT,
  PRIMARY KEY (run_id, hid)
);
"""


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def research_dir(run_id: str) -> Path:
    p = RESEARCH_ROOT / run_id
    p.mkdir(parents=True, exist_ok=True)
    (p / "evidence").mkdir(exist_ok=True)
    return p


def open_research_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    return con


def register_params(h: int, universe: str, rhos: dict[str, float], extra: dict) -> dict:
    return {
        "schema": "regime-ic-v4",
        "horizon": h,
        "universe": universe,
        "factors": list(FACTORS),
        "states": list(STATES),
        "hypothesis_ids": list(RS.HYPOTHESIS_IDS),
        "warmup": RD.WARMUP_DAYS,
        "ic_min_cross": RD.MIN_CROSS,
        "ic_min_frac": RD.MIN_MEMBER_FRAC,
        "holm_m": RS.M_HOLM,
        "bandwidth": "L1=max(h-1,ceil(T^{1/3})); L2=max(2L1,20)",
        "price_tag": "price_return_ex_dividend",
        "rho": rhos,
        "software": {"ic_eval": "ic_eval_v1_1", "regime": "v4"},
        **extra,
    }


def run_v4(
    *,
    bars: dict,
    members_on: dict[str, set[str]],
    horizon: int,
    universe_name: str,
    blocked: dict[str, str] | None = None,
    run_id: str | None = None,
    out_root: Path | None = None,
) -> dict:
    run_id = run_id or new_run_id()
    root = Path(out_root) if out_root else research_dir(run_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / "evidence").mkdir(exist_ok=True)
    dbp = root / "regime_ic.db"
    logp = root / "research_log.jsonl"
    blocked = blocked or {}
    calendar = RD.trading_dates(bars)
    eligible = RD.eligible_dates(calendar, horizon)
    fwd = RD.forward_close(bars, horizon)
    daily: dict[str, dict[str, float]] = {}
    rhos: dict[str, float] = {}
    for fac in FACTORS:
        fv = IE.FACTORS[fac](bars)
        pack = RD.daily_ic_v4(fv, fwd, members_on=members_on, dates=eligible)
        daily[fac] = pack["ics"]
        series = [pack["ics"][d] for d in eligible if d in pack["ics"]]
        raw_rho = RD.acf1(series)
        rhos[fac] = RD.rho_hat_or_default(raw_rho)
        rhos[f"{fac}_acf1"] = raw_rho
    univ_for_width = sorted({s for v in members_on.values() for s in v}) if members_on else [s for s in bars if s != "SPY"]
    labels = {
        "trend": RG.trend_spy(bars),
        "width": RG.width_sp500(bars, univ_for_width or list(bars.keys()), members_on=members_on),
        "vol": RG.vol_spy(bars),
    }

    params = register_params(horizon, universe_name, {k: rhos[k] for k in FACTORS}, {
        "run_id": run_id,
        "calendar_first": calendar[0] if calendar else None,
        "calendar_last": calendar[-1] if calendar else None,
        "eligible_n": len(eligible),
    })
    (root / "parameters.json").write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")

    con = open_research_db(dbp)
    con.execute(
        "INSERT INTO run(run_id,status,started,params) VALUES(?,?,?,?)",
        (run_id, "running", datetime.now(timezone.utc).isoformat(), json.dumps(params)),
    )
    con.commit()
    try:
        p_raw: dict[str, float | None] = {}
        results: dict[str, dict] = {}
        for fac in FACTORS:
            for st in STATES:
                hid = f"{fac}.{st}"
                if hid in blocked or universe_name.endswith("_blocked") or blocked.get("universe"):
                    results[hid] = {
                        "verdict": "blocked",
                        "reason": blocked.get(hid) or blocked.get("universe") or "universe blocked",
                        "p_L1": None, "p_L2": None, "p_robust": None, "p_holm": None,
                    }
                    p_raw[hid] = None
                    continue
                y = daily[fac]
                lab = labels[st]
                buckets = RS.TREND_BUCKETS if st == "trend" else RS.THREE_BUCKETS
                L1, L2 = RS.bandwidths(len(eligible), horizon)
                cov = RS.coverage_ok(
                    eligible_days=eligible, ic_dates=set(y), labels=lab,
                    buckets=buckets, L2=L2,
                )
                jt = RS.joint_test(eligible, y, lab, st, horizon)
                insuff = (not cov["ok"]) or (not jt.get("ok"))
                p_raw[hid] = None if insuff or not jt.get("ok") else jt.get("p_robust")
                results[hid] = {
                    "factor": fac, "state": st,
                    "coverage": cov,
                    "joint_ok": jt.get("ok"),
                    "reason": None if jt.get("ok") else jt.get("reason"),
                    "L1": L1, "L2": L2,
                    "p_L1": jt.get("p_L1"), "p_L2": jt.get("p_L2"),
                    "p_robust": jt.get("p_robust"),
                    "W_L1": jt.get("W_L1"), "W_L2": jt.get("W_L2"),
                    "b": jt.get("b"),
                    "desc_ci": jt.get("desc_ci"),
                    "buckets": list(buckets),
                    "insufficient": insuff,
                }
        holm = RS.holm(p_raw)
        for hid, rec in results.items():
            if rec.get("verdict") == "blocked":
                rec["p_holm"] = holm[hid]["p_holm"]
                continue
            rec["p_holm"] = holm[hid]["p_holm"]
            rec["p_raw"] = holm[hid]["p_raw"]
            rec["verdict"] = RS.verdict(False, rec.get("insufficient", True), holm[hid]["p_holm"] if holm[hid]["p_raw"] is not None else None)

        for fac, ics in daily.items():
            for d, ic in ics.items():
                con.execute(
                    "INSERT INTO daily_ic(run_id,d,factor,ic,n) VALUES(?,?,?,?,?)",
                    (run_id, d, fac, ic, None),
                )
        for hid, rec in results.items():
            payload = json.dumps(rec, ensure_ascii=False, default=str)
            con.execute("INSERT INTO hypothesis_results(run_id,hid,payload) VALUES(?,?,?)", (run_id, hid, payload))
            con.execute("INSERT INTO bucket_stats(run_id,hid,payload) VALUES(?,?,?)", (run_id, hid, payload))
        con.execute(
            "UPDATE run SET status=?, finished=? WHERE run_id=?",
            ("complete", datetime.now(timezone.utc).isoformat(), run_id),
        )
        con.commit()
    except Exception:
        con.execute("UPDATE run SET status=? WHERE run_id=?", ("incomplete", run_id))
        con.commit()
        raise
    finally:
        con.close()

    report = {
        "run_id": run_id,
        "params": params,
        "results": results,
        "rho": rhos,
        "eligible_n": len(eligible),
    }
    (root / "REPORT.md").write_text(_render_report(report), encoding="utf-8")
    with logp.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "run_id": run_id, "status": "complete"}, ensure_ascii=False) + "\n")
    return report


def _render_report(rep: dict) -> str:
    lines = [f"# regime IC v4 · {rep['run_id']}", "", f"universe={rep['params']['universe']} h={rep['params']['horizon']}", ""]
    lines.append("| hid | verdict | p_L1 | p_L2 | p_holm |")
    lines.append("|---|---|---:|---:|---:|")
    for hid in RS.HYPOTHESIS_IDS:
        r = rep["results"][hid]
        def f(x):
            return "—" if x is None else f"{x:.4g}"
        lines.append(f"| {hid} | {r['verdict']} | {f(r.get('p_L1'))} | {f(r.get('p_L2'))} | {f(r.get('p_holm'))} |")
    return "\n".join(lines) + "\n"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return center - half, center + half


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db")
    ap.add_argument("--universe")
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--start", default="2023-01-03")
    ap.add_argument("--end")
    ap.add_argument("--run-id")
    a = ap.parse_args(argv)
    if not a.db or not a.universe:
        print("need --db and --universe")
        return 2
    symbols = IE._load_universe(a.universe)
    con = RD.connect_ro(a.db)
    try:
        loaded = RD.load_bars_research(con, symbols=symbols + ["SPY"], start=a.start, end=a.end)
    finally:
        con.close()
    blocked = {}
    if loaded.get("blocked"):
        blocked["universe"] = loaded.get("reason") or "src blocked"
    bars = loaded.get("bars") or {}
    # without PIT events this is NOT sp500_pit
    univ_name = "sp500_pit" if not blocked else "sp500_pit"
    if blocked:
        # still record a blocked run so the receipt has a path
        members = {d: set(symbols) for d in RD.trading_dates(bars)} if bars else {}
        if not bars:
            RESEARCH_ROOT.mkdir(parents=True, exist_ok=True)
            rid = a.run_id or new_run_id()
            root = research_dir(rid)
            (root / "parameters.json").write_text(json.dumps({
                "universe": "sp500_pit", "blocked": blocked, "horizon": a.horizon,
            }, indent=2), encoding="utf-8")
            (root / "REPORT.md").write_text(
                f"# regime IC v4 · {rid}\n\nblocked: {blocked}\n", encoding="utf-8"
            )
            print(json.dumps({"run_id": rid, "blocked": blocked, "dir": str(root)}, ensure_ascii=False))
            return 0
        rep = run_v4(
            bars=bars, members_on=members, horizon=a.horizon,
            universe_name="sp500_pit", blocked=blocked, run_id=a.run_id,
        )
        print(json.dumps({"run_id": rep["run_id"], "blocked": blocked}, ensure_ascii=False))
        return 0
    members = {d: set(symbols) for d in RD.trading_dates(bars)}
    blocked["universe"] = "sp500_pit not reconstructed (no constituent events); current-list is not PIT"
    rep = run_v4(
        bars=bars, members_on=members, horizon=a.horizon,
        universe_name="sp500_pit", blocked=blocked, run_id=a.run_id,
    )
    print(json.dumps({"run_id": rep["run_id"], "verdicts": {h: rep["results"][h]["verdict"] for h in RS.HYPOTHESIS_IDS}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
