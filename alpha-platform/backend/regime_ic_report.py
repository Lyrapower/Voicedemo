"""4 factors × 3 regimes → 12 small IC tables. Does not write platform.db. Optional lineage ALTER only."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ic_eval_v1_1 as IE  # noqa: E402
import regime as RG  # noqa: E402

FACTORS = ("mom_5", "mom_20", "rev_1", "vol_20")
REGIMES = ("trend", "breadth", "vol")


def _fmt(x, d=4):
    if x is None:
        return "—"
    return f"{x:.{d}f}"


def run(db: str, universe_path: str, horizon: int, start: str | None, end: str | None) -> dict:
    symbols = IE._load_universe(universe_path)
    need = list(dict.fromkeys(symbols + ["SPY"]))
    bars = IE.load_bars(db, start, end, symbols=need, exclude_src=("alpaca_iex",))
    univ_bars = {s: bars[s] for s in symbols if s in bars}
    out = {
        "horizon": horizon,
        "min_n": IE.MIN_N,
        "universe_n": len(symbols),
        "symbols_loaded": len(univ_bars),
        "spy_n": len(bars.get("SPY") or []),
        "tables": {},
        "one_liners": {},
    }
    for kind in REGIMES:
        labels = RG.labels_for(kind, bars, universe=symbols)
        out["tables"][kind] = {}
        for name in FACTORS:
            pack = IE.evaluate_regime(univ_bars, IE.FACTORS[name], horizon, labels)
            rows = []
            watches = []
            flips = []
            insuff = []
            rejects = []
            for lab, s in pack["buckets"].items():
                rows.append({
                    "bucket": lab,
                    "n": s["n_obs"],
                    "ic": s["ic_mean"],
                    "t": s["ic_t"],
                    "half_a": s["half_a"].get("ic_mean"),
                    "half_b": s["half_b"].get("ic_mean"),
                    "verdict": s["verdict"],
                    "reason": s["reason"],
                })
                v = s["verdict"]
                if v.startswith("watch"):
                    watches.append(f"{lab}:{v}")
                elif v == "regime_flip":
                    flips.append(lab)
                elif v == "insufficient":
                    insuff.append(lab)
                else:
                    rejects.append(lab)
            out["tables"][kind][name] = {
                "full": {k: pack["full"].get(k) for k in ("n_obs", "ic_mean", "ic_t")},
                "buckets": rows,
            }
            if flips:
                line = f"{name}/{kind}: regime_flip @ {','.join(flips)}"
            elif watches:
                line = f"{name}/{kind}: " + "; ".join(watches)
            elif insuff and not rejects:
                line = f"{name}/{kind}: all insufficient"
            else:
                line = f"{name}/{kind}: reject ({','.join(rejects) or 'none'}) insuff={','.join(insuff) or 'none'}"
            out["one_liners"][f"{name}:{kind}"] = line
    return out


def render_md(pack: dict) -> str:
    lines = [
        f"horizon={pack['horizon']} min_n={pack['min_n']} universe={pack['universe_n']} "
        f"loaded={pack['symbols_loaded']} spy_rows={pack['spy_n']}",
        "",
    ]
    for kind in REGIMES:
        for name in FACTORS:
            tbl = pack["tables"][kind][name]
            full = tbl["full"]
            lines.append(f"### {name} · {kind}")
            lines.append(f"full n={full['n_obs']} ic={_fmt(full['ic_mean'])} t={_fmt(full['ic_t'], 2)}")
            lines.append("| bucket | n | IC | t | 前半 | 后半 | verdict |")
            lines.append("|---|---:|---:|---:|---:|---:|---|")
            for r in tbl["buckets"]:
                lines.append(
                    f"| {r['bucket']} | {r['n']} | {_fmt(r['ic'])} | {_fmt(r['t'], 2)} | "
                    f"{_fmt(r['half_a'])} | {_fmt(r['half_b'])} | {r['verdict']} |"
                )
            if not tbl["buckets"]:
                lines.append("| — | 0 | — | — | — | — | insufficient |")
            lines.append("")
    lines.append("## 每因子一句")
    for name in FACTORS:
        bits = [pack["one_liners"][f"{name}:{k}"] for k in REGIMES]
        lines.append(f"- {name}: " + " · ".join(bits))
    return "\n".join(lines)


def maybe_alter_lineage() -> str:
    try:
        import factor_lineage_v1_1 as FL
        con = FL.connect()
        IE._ensure_regime_cols(con)
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM evals").fetchone()[0]
        nulls = con.execute("SELECT COUNT(*) FROM evals WHERE regime IS NULL").fetchone()[0]
        con.close()
        return f"evals n={n} regime NULL={nulls} (old rows untouched)"
    except Exception as e:
        return f"lineage alter skipped: {e}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--universe", required=True)
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alter-lineage", action="store_true",
                    help="ADD COLUMN regime/bucket if missing; does not INSERT")
    a = ap.parse_args(argv[1:])
    t0 = time.time()
    pack = run(a.db, a.universe, a.horizon, a.start, a.end)
    pack["elapsed"] = round(time.time() - t0, 1)
    if a.alter_lineage:
        pack["lineage"] = maybe_alter_lineage()
    if a.json:
        print(json.dumps(pack, ensure_ascii=False, default=str))
    else:
        print(render_md(pack))
        if pack.get("lineage"):
            print(pack["lineage"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
