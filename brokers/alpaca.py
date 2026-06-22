"""
Alpaca adapter (paper + live) using the documented v2 REST API directly, so
there's no SDK version to drift on. The same code hits paper or live — only the
base URL and your keys change.

  paper: https://paper-api.alpaca.markets   (virtual money, real prices)
  live : https://api.alpaca.markets         (real money)

Market data comes from the Alpaca Data API. Free accounts use the IEX feed,
which is plenty for a daily-bar strategy.
"""

from __future__ import annotations
import datetime as dt
from typing import Dict, List

import requests

from brokers.base import Broker, Account, Position, OrderRequest
from strategy import Bar

TRADE_PAPER = "https://paper-api.alpaca.markets"
TRADE_LIVE = "https://api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"


class AlpacaBroker(Broker):
    def __init__(self, key: str, secret: str, paper: bool = True, feed: str = "iex"):
        if not key or not secret:
            raise RuntimeError("Missing Alpaca keys. Set ALPACA_API_KEY / ALPACA_API_SECRET.")
        self.name = "alpaca_paper" if paper else "alpaca_live"
        self.base = TRADE_PAPER if paper else TRADE_LIVE
        self.feed = feed
        self.h = {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "accept": "application/json",
        }

    # ---- account / positions ----
    def get_account(self) -> Account:
        r = requests.get(f"{self.base}/v2/account", headers=self.h, timeout=20)
        r.raise_for_status()
        a = r.json()
        equity = float(a["equity"])
        last_equity = float(a.get("last_equity", equity)) or equity
        day_pl_pct = (equity - last_equity) / last_equity if last_equity else 0.0
        return Account(
            equity=equity,
            cash=float(a["cash"]),
            buying_power=float(a["buying_power"]),
            day_pl_pct=day_pl_pct,
        )

    def get_positions(self) -> Dict[str, Position]:
        r = requests.get(f"{self.base}/v2/positions", headers=self.h, timeout=20)
        r.raise_for_status()
        out: Dict[str, Position] = {}
        for p in r.json():
            out[p["symbol"]] = Position(
                symbol=p["symbol"],
                qty=float(p["qty"]),
                avg_price=float(p["avg_entry_price"]),
                market_value=float(p["market_value"]),
                unrealized_pl=float(p["unrealized_pl"]),
            )
        return out

    # ---- market data ----
    def get_daily_bars(self, symbol: str, limit: int = 45) -> List[Bar]:
        start = (dt.date.today() - dt.timedelta(days=limit * 2 + 20)).isoformat()
        params = {
            "timeframe": "1Day",
            "start": start,
            "limit": limit + 5,
            "adjustment": "split",
            "feed": self.feed,
        }
        # Use single-symbol path — more reliable across free/paid tiers
        url = f"{DATA_BASE}/v2/stocks/{symbol}/bars"
        r = requests.get(url, headers=self.h, params=params, timeout=20)
        if not r.ok:
            raise RuntimeError(
                f"Alpaca data error {r.status_code} for {symbol}: {r.text[:200]}"
            )
        rows = r.json().get("bars", [])
        bars = [Bar(h=b["h"], l=b["l"], c=b["c"], v=b["v"]) for b in rows]
        return bars[-limit:]

    # ---- orders ----
    def submit_order(self, order: OrderRequest) -> dict:
        body = {
            "symbol": order.symbol,
            "qty": str(order.qty),
            "side": order.side,
            "type": order.type,
            "time_in_force": "day",
        }
        if order.type == "limit" and order.limit_price is not None:
            body["limit_price"] = str(round(order.limit_price, 2))
        if order.take_profit is not None and order.stop_loss is not None:
            body["order_class"] = "bracket"
            body["take_profit"] = {"limit_price": round(order.take_profit, 2)}
            body["stop_loss"] = {"stop_price": round(order.stop_loss, 2)}
        r = requests.post(f"{self.base}/v2/orders", headers=self.h, json=body, timeout=20)
        if r.status_code >= 300:
            raise RuntimeError(f"Alpaca order rejected ({r.status_code}): {r.text}")
        return r.json()

    def close_position(self, symbol: str) -> dict:
        r = requests.delete(f"{self.base}/v2/positions/{symbol}", headers=self.h, timeout=20)
        if r.status_code >= 300:
            raise RuntimeError(f"Alpaca close rejected ({r.status_code}): {r.text}")
        return r.json()
