"""Shared trade-action lexicon — contract_gate / momentum_sticker / watcher_bridge."""
from __future__ import annotations

import re

TRADE_ACTION_OUTPUT = re.compile(
    r"建仓|做多|做空|买入|卖出|加仓|开仓|平仓|开多|开空|平多|平空|下单",
    re.I,
)
