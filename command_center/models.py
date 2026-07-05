"""
models.py — 13 independent voting models.

Each model looks at a different dimension of market structure and returns:
  +1  BUY  — conditions favour a long entry
   0  HOLD — no clear signal
  -1  SELL — conditions favour avoiding / exiting longs

Independence matters. If all 13 use price momentum, "consensus" is just
one signal counted 13 times. These cover: trend, momentum, mean-reversion,
volume, volatility, and candle structure — distinct lenses on the same data.
"""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Vote:
    model:  str
    vote:   int    # +1, 0, -1
    value:  float  # raw indicator value
    note:   str


# ── helpers ──────────────────────────────────────────────────────────────────

def _sma(closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _ema(closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    k = 2 / (n + 1)
    ema = closes[-n]
    for c in closes[-n + 1:]:
        ema = c * k + ema * (1 - k)
    return ema


def _std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def _linreg_slope(values: List[float]) -> float:
    """Normalised linear regression slope (%/bar)."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(values) / n
    num = sum((xs[i] - mx) * (values[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    return (num / den / my * 100) if den and my else 0.0


# ── the 13 models ─────────────────────────────────────────────────────────────

def model_ma50_cross(bars: List[Bar]) -> Vote:
    """Price vs 50-day SMA. Above = bullish trend, below = bearish."""
    closes = [b.close for b in bars]
    ma = _sma(closes, 50)
    if ma is None:
        return Vote("ma50_cross", 0, 0, "insufficient data")
    price = closes[-1]
    pct = (price - ma) / ma * 100
    vote = 1 if pct > 1 else -1 if pct < -1 else 0
    return Vote("ma50_cross", vote, round(pct, 2), f"price {pct:+.1f}% vs 50-MA")


def model_macd(bars: List[Bar]) -> Vote:
    """MACD histogram (12/26/9). Positive = momentum building."""
    closes = [b.close for b in bars]
    if len(closes) < 35:
        return Vote("macd", 0, 0, "insufficient data")
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    if ema12 is None or ema26 is None:
        return Vote("macd", 0, 0, "insufficient data")
    macd_line = ema12 - ema26
    # Signal line = 9-period EMA of MACD (approximate with last values)
    prev_closes = closes[:-1]
    pe12 = _ema(prev_closes, 12) or ema12
    pe26 = _ema(prev_closes, 26) or ema26
    prev_macd = pe12 - pe26
    histogram = macd_line - prev_macd   # simplified histogram
    vote = 1 if histogram > 0 and macd_line > 0 else -1 if histogram < 0 and macd_line < 0 else 0
    return Vote("macd", vote, round(macd_line, 2), f"MACD {macd_line:+.1f} hist {histogram:+.1f}")


def model_rsi(bars: List[Bar], period: int = 14) -> Vote:
    """RSI(14). <35 = oversold/buy zone, >65 = overbought/avoid."""
    closes = [b.close for b in bars]
    if len(closes) < period + 1:
        return Vote("rsi14", 0, 0, "insufficient data")
    gains, losses = [], []
    for i in range(-period, 0):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag, al = sum(gains) / period, sum(losses) / period
    rsi = 100 - (100 / (1 + ag / al)) if al > 0 else 100
    vote = 1 if rsi < 35 else -1 if rsi > 65 else 0
    return Vote("rsi14", vote, round(rsi, 1), f"RSI {rsi:.1f}")


def model_bollinger(bars: List[Bar], period: int = 20) -> Vote:
    """Price vs Bollinger Bands (20, 2σ). Near lower band = buy zone."""
    closes = [b.close for b in bars]
    if len(closes) < period:
        return Vote("bollinger", 0, 0, "insufficient data")
    win = closes[-period:]
    mid = sum(win) / period
    sd  = _std(win)
    upper, lower = mid + 2 * sd, mid - 2 * sd
    price = closes[-1]
    band_width = upper - lower
    pct_b = (price - lower) / band_width if band_width > 0 else 0.5
    vote = 1 if pct_b < 0.2 else -1 if pct_b > 0.8 else 0
    return Vote("bollinger", vote, round(pct_b, 3), f"%B {pct_b:.2f} (0=lower, 1=upper)")


def model_stochastic(bars: List[Bar], period: int = 14) -> Vote:
    """Stochastic %K. <20 = oversold, >80 = overbought."""
    if len(bars) < period:
        return Vote("stochastic", 0, 0, "insufficient data")
    win = bars[-period:]
    highest = max(b.high for b in win)
    lowest  = min(b.low for b in win)
    price   = bars[-1].close
    k = (price - lowest) / (highest - lowest) * 100 if highest != lowest else 50
    vote = 1 if k < 20 else -1 if k > 80 else 0
    return Vote("stochastic", vote, round(k, 1), f"Stoch %K {k:.1f}")


def model_rate_of_change(bars: List[Bar], period: int = 10) -> Vote:
    """10-day price rate of change. Strong positive = momentum."""
    if len(bars) < period + 1:
        return Vote("roc10", 0, 0, "insufficient data")
    past  = bars[-(period + 1)].close
    now   = bars[-1].close
    roc   = (now - past) / past * 100
    vote  = 1 if roc > 3 else -1 if roc < -3 else 0
    return Vote("roc10", vote, round(roc, 2), f"10-day ROC {roc:+.1f}%")


def model_trend_slope(bars: List[Bar], period: int = 20) -> Vote:
    """Linear regression slope of last 20 closes, normalised to %/day."""
    if len(bars) < period:
        return Vote("trend_slope", 0, 0, "insufficient data")
    closes = [b.close for b in bars[-period:]]
    slope  = _linreg_slope(closes)
    vote   = 1 if slope > 0.15 else -1 if slope < -0.15 else 0
    return Vote("trend_slope", vote, round(slope, 3), f"slope {slope:+.3f}%/day")


def model_volume_surge(bars: List[Bar], period: int = 20) -> Vote:
    """Today's volume vs 20-day average. Surge with price up = bullish."""
    if len(bars) < period + 1:
        return Vote("volume_surge", 0, 0, "insufficient data")
    avg_vol = sum(b.volume for b in bars[-(period + 1):-1]) / period
    cur_vol = bars[-1].volume
    price_up = bars[-1].close > bars[-2].close
    ratio   = cur_vol / avg_vol if avg_vol > 0 else 1
    vote = 1 if ratio > 1.4 and price_up else -1 if ratio > 1.4 and not price_up else 0
    return Vote("volume_surge", vote, round(ratio, 2), f"vol ratio {ratio:.2f}x price {'↑' if price_up else '↓'}")


def model_volume_trend(bars: List[Bar], period: int = 10) -> Vote:
    """Is volume trending up (accumulation) or down (distribution)?"""
    if len(bars) < period:
        return Vote("volume_trend", 0, 0, "insufficient data")
    vols  = [b.volume for b in bars[-period:]]
    slope = _linreg_slope(vols)
    vote  = 1 if slope > 0.5 else -1 if slope < -0.5 else 0
    return Vote("volume_trend", vote, round(slope, 3), f"vol slope {slope:+.2f}%/day")


def model_atr_regime(bars: List[Bar], period: int = 14) -> Vote:
    """Low ATR = calm market = better for mean-reversion entries."""
    if len(bars) < period + 1:
        return Vote("atr_regime", 0, 0, "insufficient data")
    trs = []
    for i in range(-period, 0):
        h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr      = sum(trs) / len(trs)
    atr_pct  = atr / bars[-1].close * 100
    # Historical baseline: moderate ATR% — use 2% as threshold for BTC
    vote = 1 if atr_pct < 2.0 else -1 if atr_pct > 5.0 else 0
    return Vote("atr_regime", vote, round(atr_pct, 2), f"ATR {atr_pct:.2f}% ({'calm' if atr_pct < 2 else 'volatile'})")


def model_range_position(bars: List[Bar], period: int = 20) -> Vote:
    """Where is price within the 20-day high/low range? (from range_bot logic)"""
    if len(bars) < period + 2:
        return Vote("range_pos", 0, 0, "insufficient data")
    win = bars[-(period + 1):-1]
    high = max(b.high for b in win)
    low  = min(b.low for b in win)
    span = high - low or 1
    pos  = (bars[-1].close - low) / span
    vote = 1 if pos < 0.25 else -1 if pos > 0.75 else 0
    return Vote("range_pos", vote, round(pos, 3), f"range position {pos*100:.0f}%")


def model_candle_pattern(bars: List[Bar]) -> Vote:
    """Last candle body direction and relative size."""
    if len(bars) < 2:
        return Vote("candle", 0, 0, "insufficient data")
    b  = bars[-1]
    body = b.close - b.open
    full = b.high - b.low or 1
    body_pct = abs(body) / full
    if body > 0 and body_pct > 0.5:
        return Vote("candle", 1, round(body_pct, 2), f"bullish body {body_pct:.0%}")
    if body < 0 and body_pct > 0.5:
        return Vote("candle", -1, round(body_pct, 2), f"bearish body {body_pct:.0%}")
    return Vote("candle", 0, round(body_pct, 2), f"indecisive candle {body_pct:.0%}")


def model_mean_reversion_z(bars: List[Bar], period: int = 20) -> Vote:
    """Z-score of price vs 20-day mean. Extreme = mean-reversion opportunity."""
    if len(bars) < period:
        return Vote("zscore", 0, 0, "insufficient data")
    closes = [b.close for b in bars[-period:]]
    mean   = sum(closes) / period
    sd     = _std(closes)
    z      = (closes[-1] - mean) / sd if sd > 0 else 0
    vote   = 1 if z < -1.5 else -1 if z > 1.5 else 0
    return Vote("zscore", vote, round(z, 2), f"z-score {z:+.2f}")


# ── run all models ─────────────────────────────────────────────────────────────

ALL_MODELS = [
    model_ma50_cross,
    model_macd,
    model_rsi,
    model_bollinger,
    model_stochastic,
    model_rate_of_change,
    model_trend_slope,
    model_volume_surge,
    model_volume_trend,
    model_atr_regime,
    model_range_position,
    model_candle_pattern,
    model_mean_reversion_z,
]


def run_all(bars: List[Bar]) -> List[Vote]:
    """Run every model and return the full ballot."""
    return [m(bars) for m in ALL_MODELS]
