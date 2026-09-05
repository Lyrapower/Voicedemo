"""Paper 执行引擎。每一步都过风控守卫,拒绝就留痕拒绝理由。
   broker_execution 写死 False —— 永不接触真实下单。"""
from __future__ import annotations
import datetime as dt
from .account import PaperAccount, Position

BROKER_EXECUTION = False   # 写死。此引擎永不下真实订单。

class RejectedByRisk(Exception): ...

def _now() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds")

def check_entry(acc: PaperAccount, symbol: str, price: float, want_pct: float,
                marks: dict) -> tuple[bool, str]:
    """进场前风控守卫。返回 (放行?, 原因)。拒绝理由用于留痕 —— 这是审计的核心。"""
    r = acc.risk
    if symbol in acc.positions:
        return False, "already_holding"
    if len(acc.positions) >= r.max_positions:
        return False, f"max_positions({r.max_positions})_reached"
    if want_pct > r.max_position_pct:
        return False, f"position_size_{want_pct:.2f}_exceeds_cap_{r.max_position_pct}"
    eq = acc.equity(marks)
    new_exposure = acc.exposure_pct(marks) + want_pct
    if new_exposure > r.max_total_exposure_pct:
        return False, f"total_exposure_{new_exposure:.2f}_exceeds_cap_{r.max_total_exposure_pct}"
    if price * (eq * want_pct / price) > acc.cash:
        return False, "insufficient_cash"
    return True, "ok"

def enter(acc: PaperAccount, symbol: str, price: float, want_pct: float,
          reason: str, marks: dict) -> dict:
    """尝试进场。返回决策记录(无论成败都留痕)。"""
    ok, why = check_entry(acc, symbol, price, want_pct, marks)
    rec = {"ts": _now(), "action": "enter", "symbol": symbol, "price": price,
           "want_pct": want_pct, "reason": reason, "allowed": ok, "risk_note": why,
           "broker_execution": BROKER_EXECUTION}
    if not ok:
        return rec
    eq = acc.equity(marks)
    qty = round((eq * want_pct) / price, 4)
    stop = round(price * (1 - acc.risk.stop_loss_pct), 2)
    acc.positions[symbol] = Position(symbol, qty, price, _now(), reason, stop)
    acc.cash = round(acc.cash - qty * price, 2)
    rec.update({"qty": qty, "stop_price": stop, "cash_after": acc.cash})
    return rec

def check_stops(acc: PaperAccount, marks: dict) -> list[dict]:
    """检查止损。触及止损价的仓位强制离场并留痕 —— 看它的纪律执行。"""
    out = []
    for sym in list(acc.positions):
        p = acc.positions[sym]; px = marks.get(sym, p.entry_price)
        if px <= p.stop_price:
            out.append(exit_pos(acc, sym, px, "stop_loss_hit"))
    return out

def exit_pos(acc: PaperAccount, symbol: str, price: float, reason: str) -> dict:
    p = acc.positions.pop(symbol)
    pnl = round((price - p.entry_price) * p.qty, 2)
    pnl_pct = round((price / p.entry_price - 1), 4)
    acc.cash = round(acc.cash + p.qty * price, 2)
    return {"ts": _now(), "action": "exit", "symbol": symbol, "price": price,
            "reason": reason, "pnl": pnl, "pnl_pct": pnl_pct, "cash_after": acc.cash,
            "held_from": p.entry_ts, "broker_execution": BROKER_EXECUTION}
