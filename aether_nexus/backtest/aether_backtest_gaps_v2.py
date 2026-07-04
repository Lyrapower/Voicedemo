#!/usr/bin/env python3
"""
Aether Gap Backtest v2 — Thu->Fri / pre-holiday overnight-gap hypothesis test
Self-contained. Stooq keyless daily data (full 5y, no 370-day scanner limit).
NO order / hedge / broker / wallet / webhook logic. Statistics only.

Hypotheses:
  (a) thu_fri : Thu close -> Fri open (adjacent trading days, calendar diff = 1)
  (b) holiday : last trading day before market holiday close -> first post-holiday open
  baseline    : all other adjacent-trading-day overnight gaps (plain weekends included)

Sub-test:
  ex_monthly_opex : strip the whole Mon-Fri week containing each monthly OCC
  standard expiration (3rd Friday; if market closed that day, expiry = prior
  trading day — same containing week is stripped), rerun (a).
  Weekly expirations are NOT strippable by design (would zero the Thu->Fri sample);
  isolation of weekly-OpEx effects is done via the cross-sectional control group.

Cross-sectional isolation:
  target  = perilla_leaf (+ SMH) equities
  control = control_symbols.json (same sector / similar cap, monthly-only or no
            listed options — options-listing status is asserted by the user's
            control file, NOT inferred from Stooq, which has no such field)
  effect-size difference per hypothesis:
      delta = mean_effect(target) - mean_effect(control)
      where mean_effect(sym) = mean(event gaps) - mean(baseline gaps)
      bootstrap CI  : resample symbols within each group, 10k
      permutation p : shuffle symbol->group labels, 10k, two-sided
  ^SOX is an index: reported standalone, EXCLUDED from the permutation family.

Usage:
  pip install pandas numpy requests scipy   (scipy optional)
  python3 aether_backtest_gaps_v2.py --watchlist ./watchlist.json --controls ./control_symbols.json

Outputs (cwd of script):
  backtest_results.json      full stats (paste this back)
  per_symbol_results.csv     flat per-symbol table
  data_quality_report.json   coverage, missing fields, extreme/corp-action flags
  backtest_summary.md        auto numeric summary (final analysis report is written
                             separately from the pasted JSON)

Honesty guarantees:
  - ^SOX: fetched as stooq ^sox only. If unavailable or opens are degenerate
    (Open==Close everywhere -> no true opening print), it is marked
    DATA_UNAVAILABLE. No silent proxying. Any proxy must be added manually
    and will carry symbol name as given (never relabeled as SOX).
  - No fabricated data: skipped symbols are listed as skipped; small samples
    return null stats instead of numbers.
"""

from __future__ import annotations
import argparse, io, json, math, os, sys, time
import datetime as dt
import numpy as np
import pandas as pd
import requests

try:
    from scipy import stats as sps
except Exception:
    sps = None

try:
    import yfinance as yf
except Exception:
    yf = None

# ---------------- config ----------------
YEARS_BACK   = 5
BOOT_N       = 10_000
PERM_N       = 10_000
SEED         = 42
STOOQ_SLEEP  = 1.2
MIN_EVENT_N  = 8
MIN_BASE_N   = 30
EXTREME_GAP  = 0.15   # |overnight gap| beyond this -> excluded from stats, flagged in DQ
EXTREME_CC   = 0.30   # |close/close - 1| beyond this -> flagged (suspected split/corp action)
INDEX_SYMBOL = "^SOX"
ETF_SYMBOL   = "SMH"

# ---------------- data ----------------
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (aether-backtest-v2)"})

def stooq_sym(sym: str) -> str:
    s = sym.lower()
    return s if s.startswith("^") or s.endswith(".us") else s + ".us"

def _yf_ticker(sym: str) -> str:
    s = sym.upper()
    if s.startswith("^"):
        return s
    return s.replace(".US", "")

def fetch_yfinance_daily(sym: str, start: dt.date) -> pd.DataFrame | None:
    if yf is None:
        return None
    try:
        raw = yf.download(_yf_ticker(sym), start=start.isoformat(), progress=False, auto_adjust=False)
        if raw is None or raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0] for c in raw.columns]
        df = raw.reset_index()
        df = df.rename(columns={"Date": "Date", "Open": "Open", "Close": "Close"})
        if "Date" not in df.columns:
            df["Date"] = pd.to_datetime(df.index).date
        else:
            df["Date"] = pd.to_datetime(df["Date"]).dt.date
        df = df[["Date", "Open", "Close"]].dropna()
        df = df[(df["Open"] > 0) & (df["Close"] > 0)]
        df = df[df["Date"] >= start].sort_values("Date").reset_index(drop=True)
        return df if len(df) > 50 else None
    except Exception as e:
        print(f"  {sym}: yfinance error {e}", file=sys.stderr)
        return None

def fetch_daily(sym: str, start: dt.date) -> pd.DataFrame | None:
    url = f"https://stooq.com/q/d/l/?s={stooq_sym(sym)}&i=d"
    for attempt in range(3):
        try:
            r = S.get(url, timeout=15)
            if r.status_code == 200 and r.text.strip() and not r.text.lower().startswith("no data"):
                if r.text.lstrip().startswith("<!"):
                    break  # Stooq bot wall -> yfinance fallback
                df = pd.read_csv(io.StringIO(r.text))
                if {"Date", "Open", "Close"}.issubset(df.columns) and len(df) > 50:
                    df["Date"] = pd.to_datetime(df["Date"]).dt.date
                    return df[df["Date"] >= start].sort_values("Date").reset_index(drop=True)
            time.sleep(2 + 2 * attempt)
        except Exception as e:
            print(f"  {sym}: fetch error {e}", file=sys.stderr)
            time.sleep(2 + 2 * attempt)
    df = fetch_yfinance_daily(sym, start)
    if df is not None:
        print(f"  {sym}: yfinance fallback {len(df)} bars", file=sys.stderr)
    return df

# ---------------- calendar ----------------
def classify_pairs(cal: list[dt.date]) -> dict:
    cls = {}
    for i in range(1, len(cal)):
        p, c = cal[i - 1], cal[i]
        if np.busday_count(p + dt.timedelta(1), c) >= 1:
            cls[(p, c)] = "holiday"
        elif p.weekday() == 3 and c.weekday() == 4 and (c - p).days == 1:
            cls[(p, c)] = "thu_fri"
        else:
            cls[(p, c)] = "baseline"
    return cls

def third_friday(y: int, m: int) -> dt.date:
    fr = [dt.date(y, m, 1) + dt.timedelta(i) for i in range(31)
          if (dt.date(y, m, 1) + dt.timedelta(i)).month == m
          and (dt.date(y, m, 1) + dt.timedelta(i)).weekday() == 4]
    return fr[2]

def opex_week_dates(start: dt.date, end: dt.date, trading_days: set[dt.date]) -> set[dt.date]:
    """Week (Mon-Fri) containing each monthly OCC expiry. If 3rd Friday is a
    market holiday, expiry = prior trading day (same containing week)."""
    out = set()
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        exp = third_friday(y, m)
        while exp not in trading_days and exp > start:
            exp -= dt.timedelta(days=1)
        mon = exp - dt.timedelta(days=exp.weekday())
        out.update(mon + dt.timedelta(days=i) for i in range(5))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out

# ---------------- gaps + data quality ----------------
def build_gaps(sym: str, df: pd.DataFrame, valid_pairs: set, dq: dict) -> pd.DataFrame:
    miss = df["Open"].isna() | df["Close"].isna() | (df["Open"] <= 0) | (df["Close"] <= 0)
    dq[sym] = {
        "rows": int(len(df)),
        "start": str(df["Date"].min()), "end": str(df["Date"].max()),
        "missing_open_close_rows": int(miss.sum()),
        "degenerate_opens_pct": round(float((df["Open"] == df["Close"]).mean()), 4),
        "extreme_gaps_excluded": [], "suspected_corp_actions": [],
    }
    d = df.loc[~miss].reset_index(drop=True)
    dates = d["Date"].tolist(); o = d["Open"].to_numpy(); c = d["Close"].to_numpy()
    rows = []
    for i in range(1, len(dates)):
        pair = (dates[i - 1], dates[i])
        if pair not in valid_pairs:
            continue  # stale-data multi-day gap in this symbol -> drop
        gap = o[i] / c[i - 1] - 1.0
        cc = c[i] / c[i - 1] - 1.0
        if abs(cc) > EXTREME_CC:
            dq[sym]["suspected_corp_actions"].append({"date": str(dates[i]), "cc_ret": round(cc, 4)})
        if abs(gap) > EXTREME_GAP:
            dq[sym]["extreme_gaps_excluded"].append({"date": str(dates[i]), "gap": round(gap, 4)})
            continue
        rows.append((dates[i - 1], dates[i], gap))
    return pd.DataFrame(rows, columns=["prev", "curr", "gap"])

# ---------------- stats ----------------
def welch(a, b):
    if sps is not None:
        t, p = sps.ttest_ind(a, b, equal_var=False)
        return float(t), float(p)
    t = (a.mean() - b.mean()) / math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float(t), float(2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2)))))

def boot_meandiff(a, b, rng):
    d = np.empty(BOOT_N)
    for i in range(BOOT_N):
        d[i] = rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean()
    lo, hi = np.percentile(d, [2.5, 97.5])
    p = 2 * min((d <= 0).mean(), (d >= 0).mean())
    return {"ci95_bps": [round(lo * 1e4, 2), round(hi * 1e4, 2)], "p_boot": round(float(min(p, 1)), 5)}

def stats_block(ev, base, rng):
    if len(ev) < MIN_EVENT_N or len(base) < MIN_BASE_N:
        return None
    t, p = welch(ev, base)
    return {"n": int(len(ev)),
            "mean_bps": round(ev.mean() * 1e4, 2),
            "median_bps": round(float(np.median(ev)) * 1e4, 2),
            "std_bps": round(ev.std(ddof=1) * 1e4, 2),
            "win_rate": round(float((ev > 0).mean()), 4),
            "baseline_n": int(len(base)),
            "baseline_mean_bps": round(base.mean() * 1e4, 2),
            "baseline_win_rate": round(float((base > 0).mean()), 4),
            "mean_diff_bps": round((ev.mean() - base.mean()) * 1e4, 2),
            "welch_t": round(t, 3), "welch_p": round(p, 5),
            "bootstrap": boot_meandiff(ev, base, rng)}

def run_gaps(gaps: pd.DataFrame, cls: dict, opex_days: set, rng) -> dict:
    if gaps.empty:
        return {"sample": None, "thu_fri": None, "holiday": None, "thu_fri_ex_monthly_opex": None}
    lab = gaps.apply(lambda r: cls[(r["prev"], r["curr"])], axis=1).to_numpy()
    g = gaps["gap"].to_numpy()
    base = g[lab == "baseline"]
    keep = ~gaps["curr"].isin(opex_days).to_numpy()
    return {
        "sample": {"start": str(gaps["prev"].min()), "end": str(gaps["curr"].max()),
                   "date_count": int(len(gaps)) + 1, "n_gaps": int(len(gaps))},
        "thu_fri": stats_block(g[lab == "thu_fri"], base, rng),
        "holiday": stats_block(g[lab == "holiday"], base, rng),
        "thu_fri_ex_monthly_opex": stats_block(g[keep & (lab == "thu_fri")], g[keep & (lab == "baseline")], rng),
    }

def mean_effect(gaps: pd.DataFrame, cls: dict, hyp: str) -> float | None:
    if gaps.empty:
        return None
    lab = gaps.apply(lambda r: cls[(r["prev"], r["curr"])], axis=1).to_numpy()
    g = gaps["gap"].to_numpy()
    ev, base = g[lab == hyp], g[lab == "baseline"]
    if len(ev) < MIN_EVENT_N or len(base) < MIN_BASE_N:
        return None
    return float(ev.mean() - base.mean())

def group_delta(t_eff: list[float], c_eff: list[float], rng) -> dict | None:
    """delta = mean(target symbol effects) - mean(control symbol effects);
       bootstrap over symbols; permutation over group labels."""
    if len(t_eff) < 2 or len(c_eff) < 2:
        return None
    t_arr, c_arr = np.array(t_eff), np.array(c_eff)
    obs = t_arr.mean() - c_arr.mean()
    bd = np.empty(BOOT_N)
    for i in range(BOOT_N):
        bd[i] = rng.choice(t_arr, len(t_arr)).mean() - rng.choice(c_arr, len(c_arr)).mean()
    lo, hi = np.percentile(bd, [2.5, 97.5])
    pool = np.concatenate([t_arr, c_arr]); nt = len(t_arr)
    perm = np.empty(PERM_N)
    for i in range(PERM_N):
        idx = rng.permutation(len(pool))
        perm[i] = pool[idx[:nt]].mean() - pool[idx[nt:]].mean()
    p = float((np.abs(perm) >= abs(obs)).mean())
    return {"n_target_syms": len(t_arr), "n_control_syms": len(c_arr),
            "delta_bps": round(obs * 1e4, 2),
            "boot_ci95_bps": [round(lo * 1e4, 2), round(hi * 1e4, 2)],
            "permutation_p": round(p, 5)}

# ---------------- io helpers ----------------
def load_symbol_list(path: str, key: str | None) -> list[str]:
    with open(path) as f:
        data = json.load(f)
    if key and isinstance(data, dict):
        data = data.get(key, [])
    if isinstance(data, dict):  # {"symbols":[...]} or {"control_symbols":[...]}
        for k in ("symbols", "control_symbols", "control_group"):
            if k in data:
                data = data[k]; break
    out = []
    for it in data:
        s = it.get("symbol") if isinstance(it, dict) else it
        if s:
            out.append(str(s).upper())
    return out

# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watchlist", default="watchlist.json")
    ap.add_argument("--controls", default="control_symbols.json")
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)
    start = dt.date.today() - dt.timedelta(days=int(YEARS_BACK * 365.25))

    perilla = load_symbol_list(args.watchlist, "perilla_leaf") if os.path.exists(args.watchlist) else []
    control = load_symbol_list(args.controls, None) if os.path.exists(args.controls) else []
    if not perilla:
        print("!! watchlist perilla_leaf empty/missing", file=sys.stderr)
    if not control:
        print("!! control_symbols.json empty/missing — effect-size comparison will be null", file=sys.stderr)

    target_equities = list(dict.fromkeys([ETF_SYMBOL] + perilla))
    all_syms = list(dict.fromkeys([INDEX_SYMBOL] + target_equities + control))

    print(f"window {start} -> today | target {len(target_equities)} | control {len(control)}")
    frames, skipped, dq = {}, [], {}
    for sym in all_syms:
        df = fetch_daily(sym, start)
        if df is None or len(df) < 300:
            skipped.append(sym); print(f"  !! {sym}: DATA_UNAVAILABLE")
        else:
            frames[sym] = df; print(f"  {sym}: {len(df)} bars {df['Date'].min()} -> {df['Date'].max()}")
        time.sleep(STOOQ_SLEEP)

    # ^SOX degenerate-open check: no true opening print -> gaps meaningless
    sox_status = "ok"
    if INDEX_SYMBOL in frames:
        if (frames[INDEX_SYMBOL]["Open"] == frames[INDEX_SYMBOL]["Close"]).mean() > 0.5:
            sox_status = "DATA_UNAVAILABLE_degenerate_opens"
            frames.pop(INDEX_SYMBOL); skipped.append(INDEX_SYMBOL)
    else:
        sox_status = "DATA_UNAVAILABLE_no_fetch"

    cal = sorted({d for df in frames.values() for d in df["Date"]})
    if not cal:
        results = {"meta": {
            "generated": dt.datetime.now().isoformat(timespec="seconds"),
            "window": [str(start), str(dt.date.today())], "years_back": YEARS_BACK,
            "error": "no_symbol_data_all_DATA_UNAVAILABLE",
            "skipped_DATA_UNAVAILABLE": skipped, "sox_status": sox_status,
        }, "symbols": {}, "group_pooled": {}, "effect_size_target_vs_control": {}}
        with open("backtest_results.json", "w") as f:
            json.dump(results, f, indent=1, default=str)
        with open("data_quality_report.json", "w") as f:
            json.dump({"symbols": dq, "skipped": skipped, "sox_status": sox_status}, f, indent=1)
        pd.DataFrame(columns=["group", "symbol", "hypothesis"]).to_csv("per_symbol_results.csv", index=False)
        with open("backtest_summary.md", "w") as f:
            f.write("# Gap Backtest v2 — auto summary\n\n**ERROR**: no symbol data fetched.\n")
        print("\nwrote backtest_results.json / per_symbol_results.csv / data_quality_report.json / backtest_summary.md")
        return

    cls = classify_pairs(cal)
    valid = set(cls.keys())
    opex_days = opex_week_dates(cal[0], cal[-1], set(cal))

    gapsets: dict[str, pd.DataFrame] = {s: build_gaps(s, frames[s], valid, dq) for s in frames}

    groups = {"index": [s for s in [INDEX_SYMBOL] if s in frames],
              "target": [s for s in target_equities if s in frames],
              "control": [s for s in control if s in frames]}

    results = {"meta": {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "window": [str(cal[0]), str(cal[-1])], "years_back": YEARS_BACK,
        "bootstrap_n": BOOT_N, "permutation_n": PERM_N, "seed": SEED,
        "sox_status": sox_status, "proxy_used_for_sox": None,
        "groups": groups, "skipped_DATA_UNAVAILABLE": skipped,
        "extreme_gap_filter": EXTREME_GAP, "corp_action_flag_threshold": EXTREME_CC,
        "opex_definition": "monthly OCC 3rd-Friday (holiday-adjusted) containing week Mon-Fri stripped; weekly expiries isolated via control group, not stripping",
        "permutation_unit": "symbol; ^SOX excluded from permutation family",
    }, "symbols": {}, "group_pooled": {}, "effect_size_target_vs_control": {}}

    # per-symbol
    for gname, syms in groups.items():
        for s in syms:
            results["symbols"].setdefault(gname, {})[s] = run_gaps(gapsets[s], cls, opex_days, rng)
    # Bonferroni per group family (n_syms * 2 hypotheses)
    for gname, symres in results["symbols"].items():
        m = max(1, len(symres) * 2)
        results["meta"][f"bonferroni_m_{gname}"] = m
        for res in symres.values():
            for h in ("thu_fri", "holiday"):
                if res.get(h):
                    res[h]["p_bonferroni"] = round(min(1.0, res[h]["welch_p"] * m), 5)

    # group pooled = equal-weight cross-sectional mean gap per calendar pair
    for gname, syms in groups.items():
        gfs = [gapsets[s].assign(sym=s) for s in syms if not gapsets[s].empty]
        if not gfs:
            continue
        port = pd.concat(gfs).groupby(["prev", "curr"], as_index=False)["gap"].mean()
        pooled = run_gaps(port, cls, opex_days, rng)
        for h in ("thu_fri", "holiday"):
            if pooled.get(h):
                pooled[h]["p_bonferroni"] = round(min(1.0, pooled[h]["welch_p"] * 2), 5)
        results["group_pooled"][gname] = pooled

    # effect-size delta target vs control
    for h in ("thu_fri", "holiday"):
        t_eff = [e for s in groups["target"] if (e := mean_effect(gapsets[s], cls, h)) is not None]
        c_eff = [e for s in groups["control"] if (e := mean_effect(gapsets[s], cls, h)) is not None]
        results["effect_size_target_vs_control"][h] = group_delta(t_eff, c_eff, rng)

    # ---- outputs ----
    with open("backtest_results.json", "w") as f:
        json.dump(results, f, indent=1, default=str)
    with open("data_quality_report.json", "w") as f:
        json.dump({"symbols": dq, "skipped": skipped, "sox_status": sox_status}, f, indent=1)

    rows = []
    for gname, symres in results["symbols"].items():
        for s, res in symres.items():
            for h in ("thu_fri", "holiday", "thu_fri_ex_monthly_opex"):
                b = res.get(h)
                if b:
                    rows.append({"group": gname, "symbol": s, "hypothesis": h, **{k: v for k, v in b.items() if k != "bootstrap"},
                                 "boot_ci_lo_bps": b["bootstrap"]["ci95_bps"][0],
                                 "boot_ci_hi_bps": b["bootstrap"]["ci95_bps"][1],
                                 "p_boot": b["bootstrap"]["p_boot"]})
    pd.DataFrame(rows).to_csv("per_symbol_results.csv", index=False)

    with open("backtest_summary.md", "w") as f:
        f.write(f"# Gap Backtest v2 — auto summary\n\nwindow {cal[0]} -> {cal[-1]} | sox_status: {sox_status}\n\n")
        for gname, pooled in results["group_pooled"].items():
            f.write(f"## {gname} (pooled)\n\n")
            for h in ("thu_fri", "holiday", "thu_fri_ex_monthly_opex"):
                b = pooled.get(h)
                f.write(f"- **{h}**: " + ("insufficient sample\n" if not b else
                        f"n={b['n']} mean={b['mean_bps']}bps win={b['win_rate']} "
                        f"(base {b['baseline_mean_bps']}bps/{b['baseline_win_rate']}) "
                        f"welch_p={b['welch_p']} boot_p={b['bootstrap']['p_boot']}\n"))
            f.write("\n")
        f.write("## target vs control effect-size delta\n\n")
        for h, d in results["effect_size_target_vs_control"].items():
            f.write(f"- **{h}**: " + ("null (insufficient groups)\n" if not d else
                    f"delta={d['delta_bps']}bps CI{d['boot_ci95_bps']} perm_p={d['permutation_p']}\n"))
    print("\nwrote backtest_results.json / per_symbol_results.csv / data_quality_report.json / backtest_summary.md")
    print("paste backtest_results.json (+ DQ report if anything flagged) back for the analysis report")

if __name__ == "__main__":
    main()
