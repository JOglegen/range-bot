"""
Risk manager. Nothing reaches the broker without passing through here.

Two jobs:
  1. Size each position so a hit to the stop costs a fixed, small slice of
     equity (risk-based sizing), then cap that by a max % of equity per name.
  2. Enforce account-level guardrails: max concurrent positions and a daily
     loss limit that freezes new entries.
"""

from __future__ import annotations
import math
from dataclasses import dataclass

from config import Settings
from brokers.base import Account


@dataclass
class SizeDecision:
    qty: int
    reason: str   # why this size (or why zero)


class RiskManager:
    def __init__(self, s: Settings):
        self.s = s

    def can_open_new(self, account: Account, open_positions: int) -> tuple[bool, str]:
        if account.day_pl_pct <= -self.s.daily_loss_limit_pct:
            return False, (f"daily loss limit hit "
                           f"({account.day_pl_pct:.1%} <= -{self.s.daily_loss_limit_pct:.0%})")
        if open_positions >= self.s.max_open_positions:
            return False, f"position cap reached ({open_positions}/{self.s.max_open_positions})"
        return True, "ok"

    def size(self, account: Account, entry: float, stop: float) -> SizeDecision:
        if entry <= 0 or stop <= 0 or entry <= stop:
            return SizeDecision(0, "invalid entry/stop (stop must be below entry for a long)")

        per_share_risk = entry - stop
        risk_dollars = account.equity * self.s.risk_per_trade_pct
        qty_by_risk = math.floor(risk_dollars / per_share_risk)

        max_value = account.equity * self.s.max_position_pct
        qty_by_value = math.floor(max_value / entry)

        qty_by_cash = math.floor(account.buying_power / entry)

        qty = max(0, min(qty_by_risk, qty_by_value, qty_by_cash))
        if qty == 0:
            return SizeDecision(0, "sized to zero (stop too far, or account too small)")

        binding = min(
            (qty_by_risk, "1% risk budget"),
            (qty_by_value, f"{self.s.max_position_pct:.0%} position cap"),
            (qty_by_cash, "available buying power"),
            key=lambda t: t[0],
        )[1]
        return SizeDecision(qty, f"{qty} sh (limited by {binding})")
