"""
All tunable settings live here. Secrets (API keys) come from the environment,
never from this file — see .env.example.

Edit the numbers below to change behaviour. The defaults are deliberately
conservative for a small account.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    # ---- what to trade ----
    watchlist: List[str] = field(default_factory=lambda: [
        "AAPL", "MSFT", "NVDA", "AMD", "JPM", "XOM", "KO", "WMT",
    ])
    mode: str = "range"            # "range" or "breakout"
    lookback: int = 20            # trading days in the range
    min_score: int = 60           # skip setups below this setup score (0-100)

    # ---- risk controls — tuned for $1,000 paper test (issue #6) ----
    risk_per_trade_pct: float = 0.01   # risk 1% of equity per trade ($10 on $1k)
    max_position_pct: float = 0.30     # max 30% per position ($300 on $1k)
    max_open_positions: int = 3        # max 3 concurrent positions on small account
    daily_loss_limit_pct: float = 0.03 # halt new entries if down 3% on the day
    min_dollar_volume: float = 2_000_000  # liquidity floor

    # ---- execution ----
    # Bracket orders attach a stop-loss and take-profit to every entry, so exits
    # are automatic even if the bot isn't running. Strongly recommended on.
    use_bracket_orders: bool = True
    entry_order_type: str = "market"   # "market" or "limit"

    # ---- broker selection ----
    # "alpaca_paper" (default, virtual money) | "alpaca_live" | "schwab" | "mock"
    broker: str = "alpaca_paper"
    data_feed: str = "iex"             # Alpaca free-tier data feed

    # ---- Alpaca credentials (from env) ----
    alpaca_key: str = field(default_factory=lambda: _get("ALPACA_API_KEY"))
    alpaca_secret: str = field(default_factory=lambda: _get("ALPACA_API_SECRET"))

    # ---- Schwab credentials (from env) ----
    schwab_app_key: str = field(default_factory=lambda: _get("SCHWAB_APP_KEY"))
    schwab_app_secret: str = field(default_factory=lambda: _get("SCHWAB_APP_SECRET"))
    schwab_refresh_token: str = field(default_factory=lambda: _get("SCHWAB_REFRESH_TOKEN"))
    schwab_account_hash: str = field(default_factory=lambda: _get("SCHWAB_ACCOUNT_HASH"))

    def validate(self) -> None:
        if self.mode not in ("range", "breakout"):
            raise ValueError("mode must be 'range' or 'breakout'")
        if self.broker not in ("alpaca_paper", "alpaca_live", "schwab", "mock"):
            raise ValueError(f"unknown broker: {self.broker}")
        if not 0 < self.risk_per_trade_pct <= 0.05:
            raise ValueError("risk_per_trade_pct should be a small fraction, e.g. 0.01")


def load_settings() -> Settings:
    # Optional: load a local .env file if python-dotenv is installed.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    s = Settings()
    s.validate()
    return s
