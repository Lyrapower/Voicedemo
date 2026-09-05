"""heat_h.py — 断层热力 H 值 (ALPHA_FACTORY_GLM V1.2)。

H = 100 × (0.35·D + 0.25·M + 0.25·G + 0.15·V)

D 距离: price 到断层位的归一化距离(越近越大);F4 状态型:倒挂=1.0 否则 0
M 动能: 15 分钟动能归一(向断层方向)
G 结构: F1=|flip两侧GEX斜率|60日分位 / F2=OI墙绝对量60日分位 / F3=0.5 / F4=倒挂1.0
       F4 倒挂给该标的 F1/F2/F3 的 G 加成(倒挂背景下同样逼近更危险)
V 量能: vol_x20 = 当日累计量 / 过去20日同时段均量,归一到 [0,1](2×=满)
Cross 事件: 5min close 穿断层位 + V≥1.5 → H := max(H, 85)

heat_formula_v = 1.2.0
"""
from __future__ import annotations
import os
from typing import Any

HEAT_FORMULA_V = "1.2.0"
HEAT_H_THRESHOLD = float(os.getenv("HEAT_H_THRESHOLD", "70"))
PROXIMITY_BAND = float(os.getenv("HEAT_PROXIMITY_BAND", "0.015"))  # D 距离带:1.5% of spot
M_BAND = float(os.getenv("HEAT_M_BAND", "0.02"))  # M 动能归一带:2%
V_FULL = float(os.getenv("HEAT_V_FULL", "2.0"))  # V 满量:vol_x20=2×
V_CONFIRM = float(os.getenv("HEAT_V_CONFIRM", "1.5"))  # cross 事件量能确认
CROSS_FLOOR = float(os.getenv("HEAT_CROSS_FLOOR", "85"))  # cross 事件 H 下限
F4_INVERSION_BOOST = float(os.getenv("F4_INVERSION_BOOST", "0.25"))  # F4 倒挂给价位型断层 G 的加成

_W_D, _W_M, _W_G, _W_V = 0.35, 0.25, 0.25, 0.15


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _distance_d(price: float, fault_level: float | None, spot: float, *, is_state: bool, state_active: bool) -> float:
    if is_state:
        return 1.0 if state_active else 0.0
    if fault_level is None or not spot:
        return 0.0
    dist = abs(price - fault_level) / spot
    return _clamp(1.0 - dist / PROXIMITY_BAND)


def _momentum_m(ret_15m: float, fault_level: float | None, price: float) -> float:
    """向断层方向的 15min 动能归一。无断层位或恰在断层位时取 |ret_15m| 量级。"""
    if fault_level is None or not price or fault_level == price:
        return _clamp(abs(ret_15m) / M_BAND)
    toward = 1.0 if fault_level > price else -1.0
    signed = ret_15m * toward  # >0 = 朝断层
    return _clamp(signed / M_BAND)


def _structure_g(g_percentile: float | None, *, is_state: bool, state_active: bool,
                  f4_inverted: bool, fault_type: str) -> float:
    """G 结构分量。g_percentile ∈ [0,1] 由调用方从 60 日历史算;F3=0.5;F4=倒挂1.0。

    F4 倒挂给 F1/F2/F3 的 G 加成:G_boosted = G + (1−G)×BOOST(仅价位型)。
    """
    if is_state:
        return 1.0 if state_active else 0.0
    if fault_type == "F3_gap_edge":
        base = 0.5
    elif g_percentile is not None:
        base = _clamp(g_percentile)
    else:
        base = 0.5  # 无 60 日历史时回退中位
    if f4_inverted and fault_type in ("F1_gamma_flip", "F2_oi_wall", "F3_gap_edge"):
        base = base + (1.0 - base) * F4_INVERSION_BOOST
    return _clamp(base)


def _volume_v(vol_x20: float | None) -> float:
    if vol_x20 is None or vol_x20 <= 0:
        return 0.0
    return _clamp(vol_x20 / V_FULL)


def compute_heat(symbol: str, fault_type: str, fault_level: float | None, *,
                 price: float, spot: float, ret_15m: float, vol_x20: float | None,
                 g_percentile: float | None = None, f4_inverted: bool = False,
                 crossed: bool = False) -> dict[str, Any]:
    """算单标的单断层位的 H 值。返回完整诊断 dict。

    fault_type ∈ {F1_gamma_flip, F2_oi_wall, F3_gap_edge, F4_iv_inversion}
    crossed = 5min close 已穿断层位(调用方判定)
    """
    is_state = fault_type == "F4_iv_inversion"
    state_active = f4_inverted
    D = _distance_d(price, fault_level, spot, is_state=is_state, state_active=state_active)
    M = _momentum_m(ret_15m, fault_level, price)
    G = _structure_g(g_percentile, is_state=is_state, state_active=state_active,
                     f4_inverted=f4_inverted, fault_type=fault_type)
    V = _volume_v(vol_x20)
    H = 100.0 * (_W_D * D + _W_M * M + _W_G * G + _W_V * V)
    cross_event = False
    if crossed and not is_state and (vol_x20 is not None and vol_x20 >= V_CONFIRM):
        cross_event = True
        H = max(H, CROSS_FLOOR)
    return {
        "symbol": symbol,
        "fault_type": fault_type,
        "fault_level": fault_level,
        "H": round(H, 2),
        "D": round(D, 4), "M": round(M, 4), "G": round(G, 4), "V": round(V, 4),
        "vol_x20": round(vol_x20, 3) if vol_x20 is not None else None,
        "ret_15m": round(ret_15m, 5),
        "f4_inverted": f4_inverted,
        "crossed": crossed,
        "cross_event": cross_event,
        "heat_formula_v": HEAT_FORMULA_V,
        "threshold": HEAT_H_THRESHOLD,
        "hot": H >= HEAT_H_THRESHOLD,
    }


def should_push(heat: dict[str, Any]) -> bool:
    """H ≥ 阈值 或 cross 事件 → 推送。"""
    return bool(heat.get("hot") or heat.get("cross_event"))
