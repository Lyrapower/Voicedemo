"""fault_lines.py — 断层位定版 (ALPHA_FACTORY_GLM V1.2)。

05:45 ET 用 T−1 EOD 期权链(Theta OI+greeks)计算 F1/F2/F4,落盘 data/faultlines/{date}.json。
盘中断层位不漂移(位是死的,热力是活的)。可复盘、无未来函数。

F1 Gamma 翻转位(gex_flip): 沿现货价扫描累计 GEX 由正转负的价位 + 两侧 GEX 斜率
F2 OI 墙(oi_wall_call/put): 单一行权价 OI 占全链同侧 OI 比重 top3 且绝对量 ≥全链 OI 5%
F3 gap 边界(gap_edge): 当日开盘 gap ≥1.5×ATR14 的 gap 上/下沿(辅助类,06:31 首 bar / 盘前扫描后定版)
F4 IV 期限结构倒挂(状态型): 近月/次月 ATM IV 比值,基线 05:45 跟着定版,盘中每 30min 刷

PIT 口径: OI 为 OCC T+1 发布 → 当日断层位由 T−1 OI 定版,盘中活变量只有价格/量能/IV。
"""
from __future__ import annotations
import os, json, hashlib, datetime
from typing import Any
from pathlib import Path

import theta_options

FAULTLINE_OI_FLOOR_PCT = float(os.getenv("FAULTLINE_OI_FLOOR_PCT", "0.05"))  # OI 墙绝对量地板:全链 OI 的 5%
FAULTLINE_WALL_TOPN = int(os.getenv("FAULTLINE_WALL_TOPN", "3"))
HEAT_FORMULA_V = os.getenv("HEAT_FORMULA_V", "1.2.0")

_DEFAULT_DIR = Path(os.getenv("FAULTLINE_DIR", str(Path(__file__).resolve().parent.parent / "data" / "faultlines")))


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:16]


def _gex_slope_at_flip(per_strike_gex: dict[str, float], flip: float | None) -> dict[str, float | None] | None:
    """flip 位两侧 GEX 斜率(左/右导数),供 G 分量 60 日分位用。per_strike_gex 键为 str。"""
    if flip is None or not per_strike_gex:
        return None
    items = sorted((float(k), v) for k, v in per_strike_gex.items())
    ks = [k for k, _ in items]
    gex = {k: v for k, v in items}
    left_k = max((k for k in ks if k < flip), default=None)
    right_k = min((k for k in ks if k > flip), default=None)
    left = right = None
    if left_k is not None and flip != left_k:
        left = (gex.get(flip, 0.0) - gex[left_k]) / (flip - left_k)
    if right_k is not None and right_k != flip:
        right = (gex[right_k] - gex.get(flip, 0.0)) / (right_k - flip)
    avg = None
    if left is not None or right is not None:
        avg = abs((left or 0.0) + (right or 0.0)) / 2.0
    return {"left": round(left, 6) if left is not None else None,
            "right": round(right, 6) if right is not None else None,
            "abs_avg": round(avg, 6) if avg is not None else None}


def compute_f1_gamma_flip(surface: dict[str, Any]) -> dict[str, Any] | None:
    """F1 · Gamma 翻转位。返回 {level, gex_slope} 或 None。"""
    flip = surface.get("gamma_flip")
    if flip is None:
        return None
    return {
        "level": flip,
        "gex_slope": _gex_slope_at_flip(surface.get("per_strike_gex") or {}, flip),
        "net_gex": surface.get("net_gex"),
    }


def compute_f2_oi_walls(surface: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """F2 · OI 墙。同侧 OI topN 且绝对量 ≥ 全链 OI × FLOOR_PCT。返回 {call:[...], put:[...]}。"""
    per_strike_oi = surface.get("per_strike_oi") or {}
    total_oi = surface.get("total_oi") or 0
    floor_abs = total_oi * FAULTLINE_OI_FLOOR_PCT
    out: dict[str, list[dict[str, Any]]] = {"call": [], "put": []}
    if total_oi <= 0 or not per_strike_oi:
        return out
    for side in ("call", "put"):
        rows = []
        for k_s, slot in per_strike_oi.items():
            if not isinstance(slot, dict):
                continue
            oi = int(slot.get(side, 0) or 0)
            if oi <= 0:
                continue
            rows.append({"K": float(k_s), "oi": oi, "share": round(oi / total_oi, 4)})
        rows.sort(key=lambda r: r["oi"], reverse=True)
        top = rows[:FAULTLINE_WALL_TOPN]
        out[side] = [r for r in top if r["oi"] >= floor_abs]
    return out


def compute_f4_iv_inversion(surface: dict[str, Any]) -> dict[str, Any] | None:
    """F4 · IV 期限结构倒挂(状态型)。近月/次月 ATM IV 比值。倒挂 = near_iv ≥ next_iv(ratio ≥ 1)。

    返回 {near_iv, next_iv, near_exp, next_exp, ratio, inverted} 或 None(无近次月)。
    """
    nn = surface.get("near_next_iv")
    if not nn or nn.get("near") is None or nn.get("next") is None:
        return None
    near, next_ = float(nn["near"]), float(nn["next"])
    ratio = near / next_ if next_ > 0 else None
    return {
        "near_iv": round(near, 4),
        "next_iv": round(next_, 4),
        "near_exp": nn.get("near_exp"),
        "next_exp": nn.get("next_exp"),
        "ratio": round(ratio, 4) if ratio is not None else None,
        "inverted": bool(ratio is not None and ratio >= 1.0),
    }


def compute_f3_gap_edge(today_open: float, prev_close: float, atr14: float) -> dict[str, Any] | None:
    """F3 · gap 边界(辅助类)。|gap| ≥ 1.5×ATR14 → 记 gap 上/下沿。返回 None = gap 不够大。"""
    if not atr14 or atr14 <= 0 or not prev_close or prev_close <= 0 or today_open is None:
        return None
    gap = today_open - prev_close
    if abs(gap) < 1.5 * atr14:
        return None
    if gap > 0:  # gap up: 区间 [prev_close, open]
        return {"upper": today_open, "lower": prev_close, "gap": round(gap, 4),
                "gap_atr": round(abs(gap) / atr14, 2), "direction": "up"}
    return {"upper": prev_close, "lower": today_open, "gap": round(gap, 4),
            "gap_atr": round(abs(gap) / atr14, 2), "direction": "down"}


def build_fault_lines(root: str, date: str, spot: float, *, surface: dict[str, Any] | None = None,
                      base: str | None = None) -> dict[str, Any]:
    """05:45 定版:用 T−1 EOD surface 算 F1/F2/F4。F3 留空(06:31 首 bar / 盘前扫描后补)。

    返回单标的断层位 dict(未落盘)。surface 可预传避免重复拉。
    """
    surf = surface or theta_options.fetch_option_surface(root, date, spot, base=base)
    if surf is None:
        return {"symbol": root, "date": date, "spot": spot, "available": False,
                "heat_formula_v": HEAT_FORMULA_V}
    f1 = compute_f1_gamma_flip(surf)
    f2 = compute_f2_oi_walls(surf)
    f4 = compute_f4_iv_inversion(surf)
    return {
        "symbol": root,
        "date": date,
        "spot": round(spot, 4),
        "available": True,
        "heat_formula_v": HEAT_FORMULA_V,
        "theta_date": surf.get("date"),
        "n_contracts": surf.get("n_contracts"),
        "total_oi": surf.get("total_oi"),
        "oi_available": surf.get("oi_available"),
        "faults": {
            "F1_gamma_flip": f1,
            "F2_oi_walls": f2,
            "F2_max_pain": surf.get("max_pain"),
            "F3_gap_edge": None,  # 06:31 首 bar / 盘前扫描后补
            "F4_iv_inversion": f4,
        },
    }


def merge_f3(date: str, symbol: str, f3: dict[str, Any] | None, *, out_dir: Path | None = None) -> bool:
    """06:31 首 bar / 盘前扫描后,把 F3 gap 边界补进当日 faultlines 文件。返回是否更新。"""
    fp = _faultline_path(date, out_dir)
    if not fp.exists():
        return False
    payload = json.loads(fp.read_text(encoding="utf-8"))
    sym_block = next((s for s in payload.get("symbols", []) if s.get("symbol") == symbol), None)
    if sym_block is None:
        return False
    sym_block.setdefault("faults", {})["F3_gap_edge"] = f3
    payload["fingerprint"] = fingerprint({"symbols": payload["symbols"], "v": HEAT_FORMULA_V})
    payload["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _atomic_write(fp, payload)
    return True


def update_f4_intraday(date: str, symbol: str, f4_state: dict[str, Any] | None, *, out_dir: Path | None = None) -> bool:
    """盘中每 30min 刷 F4 IV 倒挂状态(状态型断层,位可变)。返回是否更新。"""
    fp = _faultline_path(date, out_dir)
    if not fp.exists():
        return False
    payload = json.loads(fp.read_text(encoding="utf-8"))
    sym_block = next((s for s in payload.get("symbols", []) if s.get("symbol") == symbol), None)
    if sym_block is None:
        return False
    sym_block.setdefault("faults", {})["F4_iv_inversion"] = f4_state
    payload["fingerprint"] = fingerprint({"symbols": payload["symbols"], "v": HEAT_FORMULA_V})
    payload["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _atomic_write(fp, payload)
    return True


def _faultline_path(date: str, out_dir: Path | None = None) -> Path:
    d = out_dir or _DEFAULT_DIR
    return d / f"{date}.json"


def _atomic_write(fp: Path, payload: dict) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical(payload)
    tmp = fp.with_suffix(".tmp")
    tmp.write_text(raw + "\n", encoding="utf-8")
    os.replace(tmp, fp)


def persist_fault_lines(date: str, symbols_data: list[dict[str, Any]], *, out_dir: Path | None = None) -> Path:
    """落盘 data/faultlines/{date}.json,带数据窗口 + 指纹(逐字节可复现)。"""
    payload = {
        "date": date,
        "v": HEAT_FORMULA_V,
        "pit_note": "OI 为 OCC T+1 → 断层位由 T−1 OI 定版,盘中活变量仅价格/量能/IV",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "symbols": symbols_data,
    }
    payload["fingerprint"] = fingerprint({"symbols": symbols_data, "v": HEAT_FORMULA_V})
    fp = _faultline_path(date, out_dir)
    _atomic_write(fp, payload)
    return fp


def load_fault_lines(date: str, *, out_dir: Path | None = None) -> dict[str, Any] | None:
    fp = _faultline_path(date, out_dir)
    if not fp.exists():
        return None
    payload = json.loads(fp.read_text(encoding="utf-8"))
    # 指纹核验(可复现)
    expected = fingerprint({"symbols": payload.get("symbols", []), "v": payload.get("v", HEAT_FORMULA_V)})
    payload["_fingerprint_ok"] = (expected == payload.get("fingerprint"))
    return payload


def verify_reproducible(date: str, *, out_dir: Path | None = None) -> bool:
    """验收用:重算当日指纹与落盘指纹逐字节比对。"""
    loaded = load_fault_lines(date, out_dir=out_dir)
    if not loaded:
        return False
    return bool(loaded.get("_fingerprint_ok"))
