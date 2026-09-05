"""Paper 账户。与真实 broker 物理隔离:此模块不 import 任何下单/密钥模块。
   $1000 模拟额度,风控按真钱配(否则学不到真避险)。"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import datetime as dt

# 风控规则 —— 按真钱设,即使是 paper(这样学到的纪律能迁移)
@dataclass
class RiskLimits:
    max_position_pct: float = 0.20      # 单笔最多占账户 20%
    max_total_exposure_pct: float = 0.60  # 总敞口最多 60%(留现金缓冲)
    stop_loss_pct: float = 0.15         # 单笔止损 15%
    max_positions: int = 4              # 最多同时持仓数

@dataclass
class Position:
    symbol: str
    qty: float
    entry_price: float
    entry_ts: str
    reason: str                          # 进场理由(留痕)
    stop_price: float

@dataclass
class PaperAccount:
    mode: str = "paper"                  # 恒为 paper,守卫检查这个
    cash: float = 1000.0
    start_equity: float = 1000.0
    positions: dict = field(default_factory=dict)
    risk: RiskLimits = field(default_factory=RiskLimits)

    def __post_init__(self):
        assert self.mode == "paper", "SAFETY: 此账户只能是 paper 模式"

    def equity(self, marks: dict[str, float]) -> float:
        """账户总值 = 现金 + 持仓市值。marks: {symbol: 现价}"""
        pos_val = sum(p.qty * marks.get(s, p.entry_price) for s, p in self.positions.items())
        return round(self.cash + pos_val, 2)

    def exposure_pct(self, marks: dict[str, float]) -> float:
        eq = self.equity(marks)
        pos_val = sum(p.qty * marks.get(s, p.entry_price) for s, p in self.positions.items())
        return round(pos_val / eq, 3) if eq > 0 else 0.0
