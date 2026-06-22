"""
Broker interface. Every adapter (Alpaca, Schwab, Mock) implements the same
small set of methods, so the runner never knows or cares which broker it's
talking to. Swap brokers by changing one line of config.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional

from strategy import Bar


@dataclass
class Account:
    equity: float
    cash: float
    buying_power: float
    # P&L on the day as a fraction of equity, e.g. -0.012 = down 1.2%.
    day_pl_pct: float


@dataclass
class Position:
    symbol: str
    qty: float
    avg_price: float
    market_value: float
    unrealized_pl: float


@dataclass
class OrderRequest:
    symbol: str
    qty: float
    side: str                      # "buy" or "sell"
    type: str = "market"           # "market" or "limit"
    limit_price: Optional[float] = None
    take_profit: Optional[float] = None   # bracket leg
    stop_loss: Optional[float] = None     # bracket leg


class Broker(ABC):
    name: str = "broker"

    @abstractmethod
    def get_account(self) -> Account: ...

    @abstractmethod
    def get_positions(self) -> Dict[str, Position]: ...

    @abstractmethod
    def get_daily_bars(self, symbol: str, limit: int = 45) -> List[Bar]: ...

    @abstractmethod
    def submit_order(self, order: OrderRequest) -> dict: ...

    @abstractmethod
    def close_position(self, symbol: str) -> dict: ...
