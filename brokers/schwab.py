"""
Schwab adapter (the live target). Built against Schwab's documented Trader API
shape. It is structurally complete but UNTESTED against a live account, because
it needs your developer app and a one-time browser authorization first.

ONE-TIME SETUP (do this before flipping broker to "schwab"):
  1. Have a Schwab brokerage account and enable thinkorswim on it.
  2. Register an Individual Developer app at developer.schwab.com.
     Add the "Accounts and Trading Production" and "Market Data Production"
     products. Set the callback URL to https://127.0.0.1. Approval takes a
     few days.
  3. Run the one-time OAuth flow (see get_schwab_refresh_token() below) to
     obtain a refresh token, and put it in SCHWAB_REFRESH_TOKEN.
  4. Fetch your account hash once and put it in SCHWAB_ACCOUNT_HASH.

Operational reality: the refresh token is only good for ~7 days, after which
you must redo the browser login. For an always-on bot you'll re-auth weekly.
"""

from __future__ import annotations
import base64
import datetime as dt
from typing import Dict, List, Optional

import requests

from brokers.base import Broker, Account, Position, OrderRequest
from strategy import Bar

TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
TRADER = "https://api.schwabapi.com/trader/v1"
MARKETDATA = "https://api.schwabapi.com/marketdata/v1"


class SchwabBroker(Broker):
    name = "schwab"

    def __init__(self, app_key: str, app_secret: str, refresh_token: str,
                 account_hash: str):
        if not all([app_key, app_secret, refresh_token, account_hash]):
            raise RuntimeError(
                "Schwab not configured. Set SCHWAB_APP_KEY, SCHWAB_APP_SECRET, "
                "SCHWAB_REFRESH_TOKEN and SCHWAB_ACCOUNT_HASH (see README)."
            )
        self.app_key = app_key
        self.app_secret = app_secret
        self.refresh_token = refresh_token
        self.account_hash = account_hash
        self._access_token: Optional[str] = None
        self._refresh_access_token()

    def _refresh_access_token(self) -> None:
        basic = base64.b64encode(f"{self.app_key}:{self.app_secret}".encode()).decode()
        r = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {basic}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
            timeout=20,
        )
        if r.status_code >= 300:
            raise RuntimeError(
                f"Schwab token refresh failed ({r.status_code}): {r.text}. "
                "Your refresh token may have expired (7-day limit) — re-run the "
                "one-time OAuth flow."
            )
        self._access_token = r.json()["access_token"]

    @property
    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}",
                "accept": "application/json"}

    # ---- account / positions ----
    def get_account(self) -> Account:
        r = requests.get(f"{TRADER}/accounts/{self.account_hash}",
                         headers=self._h, params={"fields": "positions"}, timeout=20)
        r.raise_for_status()
        acc = r.json()["securitiesAccount"]
        bal = acc["currentBalances"]
        equity = float(bal.get("liquidationValue", bal.get("equity", 0.0)))
        cash = float(bal.get("cashBalance", 0.0))
        bp = float(bal.get("buyingPower", cash))
        return Account(equity=equity, cash=cash, buying_power=bp, day_pl_pct=0.0)

    def get_positions(self) -> Dict[str, Position]:
        r = requests.get(f"{TRADER}/accounts/{self.account_hash}",
                         headers=self._h, params={"fields": "positions"}, timeout=20)
        r.raise_for_status()
        acc = r.json()["securitiesAccount"]
        out: Dict[str, Position] = {}
        for p in acc.get("positions", []):
            sym = p["instrument"]["symbol"]
            qty = float(p.get("longQuantity", 0.0)) - float(p.get("shortQuantity", 0.0))
            if qty == 0:
                continue
            out[sym] = Position(
                symbol=sym, qty=qty,
                avg_price=float(p.get("averagePrice", 0.0)),
                market_value=float(p.get("marketValue", 0.0)),
                unrealized_pl=float(p.get("currentDayProfitLoss", 0.0)),
            )
        return out

    # ---- market data ----
    def get_daily_bars(self, symbol: str, limit: int = 45) -> List[Bar]:
        params = {"symbol": symbol, "periodType": "month", "period": 3,
                  "frequencyType": "daily", "frequency": 1, "needExtendedHoursData": "false"}
        r = requests.get(f"{MARKETDATA}/pricehistory", headers=self._h,
                         params=params, timeout=20)
        r.raise_for_status()
        candles = r.json().get("candles", [])
        bars = [Bar(h=c["high"], l=c["low"], c=c["close"], v=c["volume"]) for c in candles]
        return bars[-limit:]

    # ---- orders ----
    def submit_order(self, order: OrderRequest) -> dict:
        leg = {
            "instruction": "BUY" if order.side == "buy" else "SELL",
            "quantity": order.qty,
            "instrument": {"symbol": order.symbol, "assetType": "EQUITY"},
        }
        if order.take_profit is not None and order.stop_loss is not None:
            # OCO bracket: entry triggers two child exit orders.
            payload = {
                "orderStrategyType": "TRIGGER",
                "session": "NORMAL", "duration": "DAY",
                "orderType": "LIMIT" if order.type == "limit" else "MARKET",
                "orderLegCollection": [leg],
                "childOrderStrategies": [{
                    "orderStrategyType": "OCO",
                    "childOrderStrategies": [
                        {"orderStrategyType": "SINGLE", "session": "NORMAL",
                         "duration": "GOOD_TILL_CANCEL", "orderType": "LIMIT",
                         "price": round(order.take_profit, 2),
                         "orderLegCollection": [{**leg, "instruction": "SELL"}]},
                        {"orderStrategyType": "SINGLE", "session": "NORMAL",
                         "duration": "GOOD_TILL_CANCEL", "orderType": "STOP",
                         "stopPrice": round(order.stop_loss, 2),
                         "orderLegCollection": [{**leg, "instruction": "SELL"}]},
                    ],
                }],
            }
        else:
            payload = {
                "orderStrategyType": "SINGLE",
                "session": "NORMAL", "duration": "DAY",
                "orderType": "LIMIT" if order.type == "limit" else "MARKET",
                "orderLegCollection": [leg],
            }
        if order.type == "limit" and order.limit_price is not None:
            payload["price"] = round(order.limit_price, 2)
        r = requests.post(f"{TRADER}/accounts/{self.account_hash}/orders",
                          headers=self._h, json=payload, timeout=20)
        if r.status_code >= 300:
            raise RuntimeError(f"Schwab order rejected ({r.status_code}): {r.text}")
        # Schwab returns the new order id in the Location header, not the body.
        return {"status": "submitted", "location": r.headers.get("Location", "")}

    def close_position(self, symbol: str) -> dict:
        pos = self.get_positions().get(symbol)
        if not pos or pos.qty == 0:
            return {"status": "no position"}
        return self.submit_order(OrderRequest(symbol=symbol, qty=abs(pos.qty), side="sell"))


def get_schwab_refresh_token(app_key: str, app_secret: str,
                             callback: str = "https://127.0.0.1") -> None:
    """One-time helper. Run this interactively to mint your first refresh token.

    Usage:
        python -c "from brokers.schwab import get_schwab_refresh_token as g; \
                   g('APPKEY','APPSECRET')"
    """
    auth_url = (f"https://api.schwabapi.com/v1/oauth/authorize?client_id={app_key}"
                f"&redirect_uri={callback}")
    print("\n1) Open this URL, log in with your Schwab account, and approve:\n")
    print("   " + auth_url + "\n")
    print("2) You'll land on a blank/'can't be reached' page. Copy the FULL URL")
    print("   from the address bar (it contains code=...).\n")
    redirected = input("Paste the full redirected URL here: ").strip()
    code = redirected.split("code=")[1].split("&")[0]
    from urllib.parse import unquote
    code = unquote(code)
    basic = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    r = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": callback},
        timeout=20,
    )
    r.raise_for_status()
    tok = r.json()
    print("\nSUCCESS. Put this in your .env as SCHWAB_REFRESH_TOKEN:\n")
    print("   " + tok["refresh_token"] + "\n")
    print("Then fetch your account hash with the /accounts/accountNumbers endpoint.")
