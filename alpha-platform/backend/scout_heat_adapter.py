#!/usr/bin/env python3
"""Seam S2 · scout morning brief → heat_nominations (source=scout); scout tree read-only."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
_DEFAULT_DB = Path(os.getenv("PLATFORM_DB", "/data/platform.db"))
if not _DEFAULT_DB.exists():
    host = _HERE.parent / "data" / "platform.db"
    if host.exists():
        _DEFAULT_DB = host
_DEFAULT_BRIEFS = Path(os.getenv(
    "SCOUT_BRIEFS",
    str(Path.home() / "Projects" / "demo" / "grid-scout" / "briefs"),
))
_ET = ZoneInfo("America/New_York")
_SYM_RX = re.compile(r"^[A-Z]{1,5}$")


def _today_et() -> dt.date:
    return dt.datetime.now(_ET).date()


def _brief_path(briefs_dir: Path, day: dt.date) -> Path:
    return briefs_dir / f"{day.isoformat()}-morning.json"


def extract_scout_noms(doc: dict[str, Any]) -> list[tuple[str, float, dict[str, Any]]]:
    """movers |chg|≥8; amc exclude double-kill (chg5>15 or rsi14>75). Returns (sym, score, meta)."""
    eng = doc.get("_engine") or {}
    out: list[tuple[str, float, dict[str, Any]]] = []
    seen: set[str] = set()

    for m in eng.get("earnings_movers") or []:
        if not isinstance(m, dict):
            continue
        sym = str(m.get("symbol") or m.get("sym") or "").upper()
        if not _SYM_RX.fullmatch(sym) or sym in seen:
            continue
        chg = m.get("chg_pct")
        try:
            chg_f = float(chg)
        except (TypeError, ValueError):
            continue
        if abs(chg_f) < 8.0:
            continue
        seen.add(sym)
        out.append((sym, abs(chg_f), {"why": "earnings_movers", "chg_pct": chg_f}))

    for a in eng.get("amc_tonight") or []:
        if isinstance(a, str):
            sym = a.upper()
            meta = {"why": "amc_tonight"}
            chg5 = rsi = None
        elif isinstance(a, dict):
            sym = str(a.get("symbol") or "").upper()
            chg5 = a.get("chg5_pct")
            rsi = a.get("rsi14")
            meta = {"why": "amc_tonight", "chg5_pct": chg5, "rsi14": rsi}
        else:
            continue
        if not _SYM_RX.fullmatch(sym) or sym in seen:
            continue
        try:
            if chg5 is not None and float(chg5) > 15.0:
                continue
            if rsi is not None and float(rsi) > 75.0:
                continue
        except (TypeError, ValueError):
            pass
        seen.add(sym)
        score = 8.0
        try:
            if a.get("chg_pct") is not None:  # type: ignore[union-attr]
                score = max(score, abs(float(a["chg_pct"])))  # type: ignore[index]
        except (TypeError, ValueError, AttributeError):
            pass
        out.append((sym, score, meta))

    out.sort(key=lambda x: -x[1])
    return out


def apply_scout_noms(c, noms: list[tuple[str, float, dict[str, Any]]], *, dry_run: bool) -> dict[str, Any]:
    """Upsert via heat_nomination schema/constants; source='scout'. No new knobs."""
    import db
    import heat_nomination as hn

    hn.ensure_schema(c)
    today = hn._today_et()
    today_s = today.isoformat()
    deny = set(db.SURFACE_DENY) | set(db.ENV_EXCLUDE)
    base = {s for s in db.BASE_WATCHLIST if s not in deny}
    cutoff = hn.scan_pool_cutoff(today)
    # Wider pool bound same as refresh_nominations (cap*3); seat ≤8 is packing-only
    pool_cap = hn.SCAN_NOMINATION_CAP * 3

    planned: list[dict[str, Any]] = []
    upserted = 0
    skipped_deny = 0
    skipped_base = 0
    skipped_pool = 0

    for sym, score, meta in noms:
        if sym in deny:
            skipped_deny += 1
            continue
        if sym in base:
            skipped_base += 1
            continue
        if upserted >= pool_cap:
            skipped_pool += 1
            planned.append({"symbol": sym, "action": "skip_pool", "score": score})
            continue
        row = c.execute(
            "SELECT first_on FROM heat_nominations WHERE symbol=?", (sym,)
        ).fetchone()
        action = "update" if row else "insert"
        planned.append({"symbol": sym, "action": action, "score": score, "meta": meta})
        upserted += 1
        if dry_run:
            continue
        meta_s = json.dumps(meta, ensure_ascii=False)
        if row:
            c.execute(
                "UPDATE heat_nominations SET last_on=?, score=?, source='scout', meta=? WHERE symbol=?",
                (today_s, float(score), meta_s, sym),
            )
        else:
            c.execute(
                "INSERT INTO heat_nominations(symbol, source, first_on, last_on, score, meta) "
                "VALUES(?,?,?,?,?,?)",
                (sym, "scout", today_s, today_s, float(score), meta_s),
            )
    if not dry_run:
        c.commit()

    scout_n = c.execute(
        "SELECT COUNT(*) FROM heat_nominations WHERE source='scout' AND last_on >= ?",
        (cutoff,),
    ).fetchone()[0]
    return {
        "asof": today_s,
        "candidates": len(noms),
        "planned": planned,
        "upserted": upserted,
        "skipped_deny": skipped_deny,
        "skipped_base": skipped_base,
        "skipped_pool": skipped_pool,
        "scout_rows": scout_n,
        "cap": hn.SCAN_NOMINATION_CAP,
        "dry_run": dry_run,
    }


def missed_movers_count(c) -> int | None:
    try:
        import factor_truth
        from missed_movers import compute_missed_movers
        import heat_nomination as hn
        import db

        sp500 = factor_truth.load_sp500_symbols()
        bfs = set(db.scan_candidate_symbols()) if hasattr(db, "scan_candidate_symbols") else set()
        movers = factor_truth._movers_from_daily_bars(c, sp500, bfs) if sp500 else {}
        gainers = movers.get("gainers") or []
        heat = hn.resolve_heat(refresh=False, conn=c)
        heat_set = set(heat.get("watchlist") or [])
        wl = set(db.BASE_WATCHLIST)
        out = compute_missed_movers(gainers, heat_set, wl)
        return int(out.get("count") or 0)
    except Exception as exc:
        print("[scout-heat] missed_movers unavailable:", str(exc)[:160])
        return None


def run(
    *,
    dry_run: bool,
    briefs_dir: Path,
    db_path: str,
    brief_path: Path | None = None,
) -> dict[str, Any]:
    os.environ.setdefault("PLATFORM_DB", db_path)
    os.environ.setdefault("SP500_SYMBOLS_CACHE", str(Path(db_path).parent / "sp500_symbols.json"))
    if not dry_run:
        os.environ.setdefault("PLATFORM_DB_DIRECT_WRITE", "1")

    today = _today_et()
    path = brief_path if brief_path is not None else _brief_path(briefs_dir, today)
    if not path.is_file():
        print(f"[scout-heat] no brief {path} — quiet exit")
        return {"status": "no_brief", "path": str(path)}

    doc = json.loads(path.read_text(encoding="utf-8"))
    noms = extract_scout_noms(doc)
    print(f"[scout-heat] brief={path.name} candidates={len(noms)}")

    import db

    c = db.conn()
    try:
        before = missed_movers_count(c)
        result = apply_scout_noms(c, noms, dry_run=dry_run)
        after = missed_movers_count(c) if not dry_run else before
    finally:
        c.close()

    result["missed_movers_before"] = before
    result["missed_movers_after"] = after
    result["brief"] = str(path)
    print("[scout-heat]", json.dumps({k: result[k] for k in result if k != "planned"}, ensure_ascii=False))
    if dry_run:
        print("[scout-heat] dry-run planned:", json.dumps(result.get("planned"), ensure_ascii=False)[:800])
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seam S2 scout→heat adapter")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--briefs", default=str(_DEFAULT_BRIEFS))
    ap.add_argument("--brief", default="", help="explicit morning.json path (ops/verify)")
    ap.add_argument("--db", default=os.getenv("PLATFORM_DB", str(_DEFAULT_DB)))
    ap.add_argument(
        "--allow-weekend",
        action="store_true",
        help="ops/verify only: run on Sat/Sun",
    )
    args = ap.parse_args(argv)

    today = _today_et()
    if today.weekday() >= 5 and not args.allow_weekend:
        print(f"[scout-heat] {today.isoformat()} weekend — skip")
        return 0

    bp = Path(args.brief) if args.brief else None
    run(
        dry_run=args.dry_run,
        briefs_dir=Path(args.briefs),
        db_path=args.db,
        brief_path=bp,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
