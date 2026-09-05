#!/usr/bin/env python3
"""Seam S1 · export SP500 factor percentile snapshot → grid-scout/inbox (read-only on factor_truth)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

# Defaults: docker /data; host alpha-platform/data; override via PLATFORM_DB / FACTOR_SNAPSHOT_OUT
_HERE = Path(__file__).resolve().parent
if os.getenv("PLATFORM_DB"):
    _DEFAULT_DB = Path(os.environ["PLATFORM_DB"])
elif Path("/data/platform.db").exists():
    _DEFAULT_DB = Path("/data/platform.db")
elif (_HERE.parent / "data" / "platform.db").exists():
    _DEFAULT_DB = _HERE.parent / "data" / "platform.db"
else:
    _DEFAULT_DB = Path("/data/platform.db")
_DEFAULT_OUT = Path(os.getenv(
    "FACTOR_SNAPSHOT_OUT",
    str(Path.home() / "Projects" / "demo" / "grid-scout" / "inbox" / "factor_snapshot.json"),
))
_ET = ZoneInfo("America/New_York")


def _trading_date() -> dt.date:
    d = dt.datetime.now(_ET).date()
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _calendar_today() -> dt.date:
    return dt.datetime.now(_ET).date()


def build_ranks(c, symbols: list[str]) -> dict[str, dict[str, float]]:
    """Reuse factor_truth closes + percentile helpers; do not write factors table."""
    import factor_truth

    raw_mom: dict[str, float] = {}
    raw_rev: dict[str, float] = {}
    raw_vol: dict[str, float] = {}
    for sym in symbols:
        closes = factor_truth._daily_closes(c, sym, 21)
        if len(closes) < 20:
            continue
        base_20 = closes[0]
        mom = (closes[-1] - base_20) / base_20 if base_20 else 0.0
        rev = (
            -(closes[-1] - closes[-6]) / closes[-6]
            if len(closes) >= 6 and closes[-6]
            else 0.0
        )
        rets = [
            (closes[i + 1] - closes[i]) / closes[i]
            for i in range(len(closes) - 1)
            if closes[i]
        ]
        vol = statistics.pstdev(rets[-20:]) * (252 ** 0.5) if len(rets) >= 2 else 0.0
        raw_mom[sym] = mom
        raw_rev[sym] = rev
        raw_vol[sym] = vol

    pct_mom = factor_truth._percentile_ranks(raw_mom)
    pct_rev = factor_truth._percentile_ranks(raw_rev)
    pct_vol = factor_truth._percentile_ranks(raw_vol)

    ranks: dict[str, dict[str, float]] = {}
    for sym in pct_mom:
        mom = round(pct_mom[sym] / 100.0, 4)
        rev = round(pct_rev.get(sym, 50.0) / 100.0, 4)
        vol = round(pct_vol.get(sym, 50.0) / 100.0, 4)
        ranks[sym] = {
            "mom": mom,
            "rev": rev,
            "vol": vol,
            "comp": round((mom + rev + vol) / 3.0, 4),
        }
    return ranks


def _load_fault_lines_block(asof: str) -> dict:
    """S1 缝:读 data/faultlines/{asof}.json,提取断层位 + 盘前热力(贴断层标记)。

    返回 {available, date, symbols:[{symbol, faults:{F1,F2,F3,F4}, near_fault}], tag}。
    scout 读此块渲染成事实行,DS prompt 标"结构参考,非信号"。
    """
    fl_dir = Path(os.getenv("FAULTLINE_DIR", str(_HERE.parent / "data" / "faultlines")))
    fp = fl_dir / f"{asof}.json"
    if not fp.exists():
        return {"available": False, "date": asof, "symbols": [], "tag": "结构参考,非信号"}
    try:
        payload = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "date": asof, "symbols": [], "tag": "结构参考,非信号"}
    out_syms = []
    for s in payload.get("symbols", []) or []:
        if not s.get("available"):
            continue
        faults = s.get("faults") or {}
        f1 = faults.get("F1_gamma_flip") or {}
        f2 = faults.get("F2_oi_walls") or {}
        f3 = faults.get("F3_gap_edge")
        f4 = faults.get("F4_iv_inversion") or {}
        out_syms.append({
            "symbol": s.get("symbol"),
            "spot": s.get("spot"),
            "F1_gamma_flip": f1.get("level") if f1 else None,
            "F2_oi_walls": {
                "call": [w.get("K") for w in (f2.get("call") or []) if w.get("K") is not None],
                "put": [w.get("K") for w in (f2.get("put") or []) if w.get("K") is not None],
            },
            "F2_max_pain": faults.get("F2_max_pain"),
            "F3_gap_edge": f3,
            "F4_iv_inversion": {
                "inverted": f4.get("inverted"),
                "ratio": f4.get("ratio"),
                "near_iv": f4.get("near_iv"),
                "next_iv": f4.get("next_iv"),
            } if f4 else None,
            "near_fault": bool(s.get("_near_fault_pushed")),
        })
    return {
        "available": True,
        "date": asof,
        "theta_date": payload.get("pit_note"),
        "symbols": out_syms,
        "tag": "结构参考,非信号",
    }


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    fd, tmp = tempfile.mkstemp(prefix=".factor_snapshot.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run(*, dry_run: bool, out_path: Path, db_path: str, pull: bool = True) -> dict:
    os.environ.setdefault("PLATFORM_DB", db_path)
    os.environ.setdefault("SP500_SYMBOLS_CACHE", str(Path(db_path).parent / "sp500_symbols.json"))

    import db
    import factor_truth

    asof = _trading_date().isoformat()
    c = db.conn()
    try:
        factor_truth.ensure_schema(c)
        symbols = factor_truth.load_sp500_symbols()
        # Never pull from host while Docker holds platform.db — dual writers corrupt SQLite.
        # Scheduled path: launchd wrapper runs inside the worker container.
        if pull and not dry_run and os.getenv("ALPHA_PLATFORM_API_PROCESS") == "1":
            if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"):
                n = factor_truth.pull_daily_bars(
                    c, symbols, limit=max(25, factor_truth.DAILY_BAR_LIMIT), skip_fresh=False
                )
                c.commit()
                print(f"[factor-snapshot] pull_daily_bars wrote_rows≈{n} universe={len(symbols)}")
            else:
                print("[factor-snapshot] ALPACA_* unset — skip pull, ranks from existing daily_bars")
        elif pull and not dry_run:
            print("[factor-snapshot] host mode — skip pull (use docker worker wrapper to backfill)")
            pull = False
        ranks = build_ranks(c, symbols)
    finally:
        c.close()

    payload = {
        "asof": asof,
        "source": "alpha-platform factor_truth",
        "ranks": ranks,
        "fault_lines": _load_fault_lines_block(asof),
    }
    summary = {
        "asof": asof,
        "n_ranks": len(ranks),
        "out": str(out_path),
        "dry_run": dry_run,
    }
    if dry_run:
        print("[factor-snapshot] dry-run — would write", json.dumps(summary, ensure_ascii=False))
        sample = list(ranks.items())[:3]
        print("[factor-snapshot] sample", sample)
        return summary

    atomic_write(out_path, payload)
    print("[factor-snapshot] wrote", out_path, "ranks=", len(ranks), "asof=", asof)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seam S1 factor snapshot exporter")
    ap.add_argument("--dry-run", action="store_true", help="print plan; no write")
    ap.add_argument("--out", default=str(_DEFAULT_OUT), help="output JSON path")
    ap.add_argument(
        "--db",
        default=os.getenv("PLATFORM_DB", str(_DEFAULT_DB)),
        help="platform.db path",
    )
    ap.add_argument(
        "--allow-weekend",
        action="store_true",
        help="ops/verify only: run on Sat/Sun",
    )
    ap.add_argument(
        "--no-pull",
        action="store_true",
        help="do not call pull_daily_bars before ranking",
    )
    args = ap.parse_args(argv)

    today = _calendar_today()
    if today.weekday() >= 5 and not args.allow_weekend:
        print(f"[factor-snapshot] {today.isoformat()} weekend — skip")
        return 0

    run(
        dry_run=args.dry_run,
        out_path=Path(args.out),
        db_path=args.db,
        pull=not args.no_pull,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
