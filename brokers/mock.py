"""
Mock broker: an in-memory fake with no network. Used by selftest.py to prove
the end-to-end wiring (data -> strategy -> risk -> order) without any keys.
You can also point the bot at it (broker="mock") to watch a full run dry.
"""

from __future__ import annotations
import math
from typing import Dict, List

from brokers.base import Broker, Account, Position, OrderRequest
from strategy import Bar


def _synth(close_fn, vol_fn, pad=0.006, n=45) -> List[Bar]:
    bars = []
    for i in range(n):
        c = close_fn(i)
        bars.append(Bar(h=c * (1 + pad), l=c * (1 - pad), c=c, v=vol_fn(i)))
    return bars


# A small set of synthetic series with known, distinct setups.
_SERIES = {
    # near the floor of a clean range -> range BUY
    "AAPL": _synth(lambda i: 210 + 6 * math.sin(i / 2.6), lambda i: 5e7),
    # broke above range high on a volume surge -> breakout BUY
    "NVDA": _synth(lambda i: (118 + i * 0.18 + 1.6 * math.sin(i / 1.7)) if i < 43
                   else 128.5 + (i - 42) * 1.1, lambda i: 7e7 if i > 42 else 2.6e7),
    # pinned at the ceiling -> range EXIT
    "AMD": _synth(lambda i: 132 + i * 0.55, lambda i: 4e7),
    # mid-range -> WAIT
    "MSFT": _synth(lambda i: 418 + 7 * math.sin(i / 3.4), lambda i: 2.1e7),
}


class MockBroker(Broker):
    name = "mock"

    def __init__(self, equity: float = 1000.0):
        self._equity = equity
        self._positions: Dict[str, Position] = {}
        self.submitted: List[OrderRequest] = []   # captured for inspection

    def get_account(self) -> Account:
        return Account(equity=self._equity, cash=self._equity,
                       buying_power=self._equity, day_pl_pct=0.0)

    def get_positions(self) -> Dict[str, Position]:
        return dict(self._positions)

    def get_daily_bars(self, symbol: str, limit: int = 45) -> List[Bar]:
        return _SERIES.get(symbol, [])[-limit:]

    def submit_order(self, order: OrderRequest) -> dict:
        self.submitted.append(order)
        self._positions[order.symbol] = Position(
            symbol=order.symbol, qty=order.qty, avg_price=0.0,
            market_value=0.0, unrealized_pl=0.0)
        return {"status": "accepted", "symbol": order.symbol, "qty": order.qty}

    def close_position(self, symbol: str) -> dict:
        self._positions.pop(symbol, None)
        return {"status": "closed", "symbol": symbol}
