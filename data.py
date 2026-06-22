"""
Data layer. Fetches historical OHLCV bars from yfinance (free, no key).
Falls back to synthetic series so the backtester can be tested offline.

yfinance is the default because:
  - free, no key, 20+ years of daily data for US equities
  - auto-adjusts for splits/dividends
  - works on any machine with internet

The backtest/strategy use the same Bar dataclass as the live bot, but here we
also carry the open price and date (needed for realistic next-open execution).
"""

from __future__ import annotations
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from strategy import Bar


@dataclass
class OHLCVBar:
    """Like Bar but adds open and date — needed for backtesting only."""
    date: date
    o: float
    h: float
    l: float
    c: float
    v: float

    def as_bar(self) -> Bar:
        return Bar(h=self.h, l=self.l, c=self.c, v=self.v)


def fetch_yfinance(symbols: List[str], start: str = "2019-01-01",
                   end: Optional[str] = None) -> Dict[str, List[OHLCVBar]]:
    """
    Download daily adjusted bars from Yahoo Finance.

    Usage:  bars = fetch_yfinance(["AAPL","MSFT"], start="2019-01-01")

    Returns a dict {symbol: [OHLCVBar, ...]}, oldest bar first.
    Silently drops any symbol that fails to download.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("Run: pip install yfinance")

    end = end or date.today().isoformat()
    raw = yf.download(symbols, start=start, end=end, auto_adjust=True,
                      progress=False, threads=True)

    result: Dict[str, List[OHLCVBar]] = {}
    is_multi = len(symbols) > 1

    for sym in symbols:
        try:
            if is_multi:
                df = raw.xs(sym, axis=1, level=1).dropna()
            else:
                df = raw.dropna()
            if df.empty:
                continue
            bars: List[OHLCVBar] = []
            for ts, row in df.iterrows():
                d = ts.date() if hasattr(ts, 'date') else ts
                bars.append(OHLCVBar(
                    date=d,
                    o=float(row["Open"]),
                    h=float(row["High"]),
                    l=float(row["Low"]),
                    c=float(row["Close"]),
                    v=float(row["Volume"]),
                ))
            result[sym] = bars
        except Exception:
            continue
    return result


# ─── Synthetic data ────────────────────────────────────────────────────────
# Generates realistic multi-regime OHLCV series for offline testing.
# Each synthetic stock cycles through: range-bound, breakout, re-range.

def _synth_one(seed: int, n_days: int = 1300, start_price: float = 100.0,
               avg_vol: float = 10_000_000) -> List[OHLCVBar]:
    """Generate a plausible multi-regime OHLCV series."""
    rng = random.Random(seed)
    bars: List[OHLCVBar] = []

    c = start_price
    today = date(2019, 1, 2)
    one = timedelta(days=1)

    regime_len = 60          # bars per regime
    regime = 0               # 0=range-bound, 1=uptrend, 2=range-bound, 3=pullback
    day_in_regime = 0
    floor = c * 0.92
    ceil  = c * 1.08

    for _ in range(n_days):
        # skip weekends
        while today.weekday() >= 5:
            today += one

        day_in_regime += 1
        if day_in_regime > regime_len:
            regime = (regime + 1) % 4
            day_in_regime = 0
            floor = c * 0.92
            ceil  = c * 1.08

        # drift + noise
        if regime == 0:   # flat, mean-revert to mid
            mid = (floor + ceil) / 2
            drift = (mid - c) * 0.05
            noise = rng.gauss(0, (ceil - floor) * 0.018)
        elif regime == 1:  # uptrend
            drift = c * 0.005
            noise = rng.gauss(0, c * 0.012)
        elif regime == 2:  # range again after trend
            floor = c * 0.94
            ceil  = c * 1.06
            mid   = (floor + ceil) / 2
            drift = (mid - c) * 0.04
            noise = rng.gauss(0, (ceil - floor) * 0.016)
        else:              # pullback / choppy
            drift = -c * 0.003
            noise = rng.gauss(0, c * 0.018)

        c = max(1.0, c + drift + noise)

        intra = c * rng.uniform(0.005, 0.018)
        o = c * (1 + rng.gauss(0, 0.004))
        h = max(o, c) + rng.uniform(0, intra)
        l = min(o, c) - rng.uniform(0, intra)
        o, h, l, c_ = round(o, 2), round(h, 2), round(l, 2), round(c, 2)
        h = max(h, o, c_)
        l = min(l, o, c_)

        vol_mult = rng.uniform(0.5, 2.0) if rng.random() < 0.1 else rng.uniform(0.7, 1.3)
        bars.append(OHLCVBar(date=today, o=o, h=h, l=l, c=c_,
                             v=round(avg_vol * vol_mult)))
        today += one

    return bars


SYNTHETIC_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMD", "JPM", "XOM", "KO", "WMT"]


def fetch_synthetic(symbols: Optional[List[str]] = None,
                    n_days: int = 1300) -> Dict[str, List[OHLCVBar]]:
    """Return synthetic OHLCV for each symbol — no internet required."""
    symbols = symbols or SYNTHETIC_SYMBOLS
    prices = [210, 420, 130, 160, 240, 108, 62, 78]
    result = {}
    for i, sym in enumerate(symbols):
        sp = prices[i % len(prices)]
        result[sym] = _synth_one(seed=i * 17 + 3, n_days=n_days, start_price=sp)
    return result


def load_data(symbols: List[str], start: str = "2019-01-01",
              offline: bool = False) -> Dict[str, List[OHLCVBar]]:
    """Top-level data loader. Tries yfinance, falls back to synthetic."""
    if offline:
        return fetch_synthetic(symbols)
    try:
        result = fetch_yfinance(symbols, start=start)
        if result:
            return result
    except Exception as e:
        print(f"[data] yfinance failed ({e}), falling back to synthetic data")
    return fetch_synthetic(symbols)
