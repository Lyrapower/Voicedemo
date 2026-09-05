"""模块② · 板块轮动(FMP · 11 SPDR vs SPY)。纯计算,零 LLM。"""
from __future__ import annotations
import os
from .http_util import http_get_json

FMP_KEY = os.getenv("FMP_API_KEY", "").strip()
SECTORS = ("XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU")
BENCH = "SPY"


def _quotes(symbols: list[str]) -> dict[str, dict]:
    # FMP stable + legacy fallback
    joined = ",".join(symbols)
    urls = [
        "https://financialmodelingprep.com/stable/batch-quote?symbols=%s&apikey=%s"
        % (joined, FMP_KEY),
        "https://financialmodelingprep.com/api/v3/quote/%s?apikey=%s"
        % (joined, FMP_KEY),
    ]
    last_err = None
    for url in urls:
        try:
            data = http_get_json(url, timeout=30)
            if isinstance(data, dict) and data.get("Error Message"):
                last_err = data["Error Message"]
                continue
            rows = data if isinstance(data, list) else data.get("quotes") or data.get("data") or []
            out = {}
            for r in rows:
                sym = r.get("symbol") or r.get("ticker")
                if sym:
                    out[sym] = r
            if out:
                return out
        except Exception as e:
            last_err = str(e)[:200]
    raise RuntimeError(last_err or "FMP quote empty")


def _chg(q: dict, key_candidates: tuple[str, ...]) -> float | None:
    for k in key_candidates:
        if q.get(k) is not None:
            try:
                return float(q[k])
            except Exception:
                pass
    # derive 1D from price/previousClose
    try:
        px = float(q.get("price") or q.get("last"))
        prev = float(q.get("previousClose") or q.get("previous_close"))
        if prev:
            return (px / prev - 1.0) * 100.0
    except Exception:
        pass
    return None


def fetch_sector_rotation() -> dict:
    if not FMP_KEY:
        return {
            "ok": False,
            "error": "FMP_API_KEY 未设置——模块② BLOCKED",
            "rows": [],
            "migration": "",
            "rule": "11 SPDR 1D/5D/20D 相对 SPY",
        }
    try:
        syms = list(SECTORS) + [BENCH]
        qs = _quotes(syms)
        spy = qs.get(BENCH) or {}
        spy_1d = _chg(spy, ("changesPercentage", "changePercentage", "change_percentage"))
        rows = []
        for s in SECTORS:
            q = qs.get(s) or {}
            d1 = _chg(q, ("changesPercentage", "changePercentage", "change_percentage"))
            # FMP quote 常无 5D/20D;标 unavailable 而非编造
            d5 = q.get("changesPercentage5D") or q.get("change_5d")
            d20 = q.get("changesPercentage20D") or q.get("change_20d")
            try:
                d5 = float(d5) if d5 is not None else None
            except Exception:
                d5 = None
            try:
                d20 = float(d20) if d20 is not None else None
            except Exception:
                d20 = None
            rel1 = None if d1 is None or spy_1d is None else round(d1 - spy_1d, 2)
            rows.append({
                "sym": s,
                "d1": None if d1 is None else round(d1, 2),
                "d5": None if d5 is None else round(d5, 2),
                "d20": None if d20 is None else round(d20, 2),
                "rel_spy_1d": rel1,
            })
        # 迁移读数:用 1D 相对强弱极值
        ranked = [r for r in rows if r["rel_spy_1d"] is not None]
        migration = ""
        if len(ranked) >= 2:
            hi = max(ranked, key=lambda x: x["rel_spy_1d"])
            lo = min(ranked, key=lambda x: x["rel_spy_1d"])
            gap = round(hi["rel_spy_1d"] - lo["rel_spy_1d"], 2)
            migration = "%s ← %s(1D 相对差 %spt)" % (hi["sym"], lo["sym"], gap)
        return {
            "ok": True,
            "error": "",
            "rows": rows,
            "migration": migration,
            "spy_1d": spy_1d,
            "note": "5D/20D 若 FMP 报价未带字段则显示 —(不编造)",
            "rule": "11 SPDR 相对 SPY",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)[:300],
            "rows": [],
            "migration": "",
            "rule": "11 SPDR 相对 SPY",
        }
