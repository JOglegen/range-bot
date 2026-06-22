"""
20-day trading-range strategy.

Pure functions, no I/O, no broker calls — this is the brain of the bot and the
one piece you should be able to read top to bottom and trust. It is a direct
port of the analytics validated in the Rangefinder tool.

Two modes:
  - "range"    : mean-reversion. Buy near the floor of an established range,
                 exit near the ceiling.
  - "breakout" : momentum. Buy when price closes above the range on heavy
                 volume; ride the measured move.

The range is built from the PRIOR `lookback` days (it excludes today), so the
latest close is always measured against a range that was established before it.
That is what makes breakout detection honest.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass
class Bar:
    h: float  # high
    l: float  # low
    c: float  # close
    v: float  # volume


@dataclass
class Metrics:
    range_high: float
    range_low: float
    mid: float
    price: float
    prev_close: float
    chg_pct: float
    pos: float          # 0..1, clamped position of price within the range
    pos_raw: float      # unclamped (>1 means broke above, <0 below)
    width_pct: float
    atr: float
    atr_pct: float
    avg_vol: float
    cur_vol: float
    vol_ratio: float
    dollar_vol: float
    trend_pct_per_day: float
    support_touches: int
    resistance_touches: int
    flatness: float
    liquidity_ok: bool
    range_score: int
    broke_up: bool
    broke_down: bool
    breakout_score: int


@dataclass
class Signal:
    tag: str                       # BUY | EXIT | WAIT | WATCH | BREAKDOWN
    note: str
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    target: Optional[float] = None
    stop: Optional[float] = None

    @property
    def is_entry(self) -> bool:
        return self.tag == "BUY"

    @property
    def is_exit(self) -> bool:
        return self.tag in ("EXIT", "BREAKDOWN")


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def compute_metrics(bars: Sequence[Bar], lookback: int = 20) -> Optional[Metrics]:
    """Return Metrics for the latest bar, or None if not enough history."""
    if len(bars) < lookback + 2:
        return None

    latest = bars[-1]
    win = bars[-(lookback + 1):-1]      # prior N bars, excludes today
    trend_win = bars[-lookback:]        # last N incl today, for drift

    highs = [b.h for b in win]
    lows = [b.l for b in win]
    vols = [b.v for b in win]

    range_high = max(highs)
    range_low = min(lows)
    mid = (range_high + range_low) / 2
    price = latest.c
    prev_close = bars[-2].c
    span = (range_high - range_low) or 1e-9
    pos_raw = (price - range_low) / span
    pos = _clamp01(pos_raw)
    width_pct = (span / range_low) * 100

    # ATR(14)
    atr_n = 14
    tr_win = bars[-(atr_n + 1):]
    trs = []
    for i in range(1, len(tr_win)):
        h, l, pc = tr_win[i].h, tr_win[i].l, tr_win[i - 1].c
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs) / len(trs)
    atr_pct = (atr / price) * 100

    # Volume
    avg_vol = sum(vols) / len(vols)
    cur_vol = latest.v
    vol_ratio = (cur_vol / avg_vol) if avg_vol > 0 else 1.0
    dollar_vol = avg_vol * price

    # Trend: linear-regression slope of closes, normalised to % per day
    closes = [b.c for b in trend_win]
    n = len(closes)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(closes) / n
    num = sum((xs[i] - mx) * (closes[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    slope = num / den if den else 0.0
    trend_pct_per_day = (slope / my) * 100

    # Boundary tests
    sup_t = sum(1 for b in win if b.l <= range_low * 1.015)
    res_t = sum(1 for b in win if b.h >= range_high * 0.985)

    # Sub-scores
    flatness = _clamp01(1 - abs(trend_pct_per_day) / 0.5)
    tested = _clamp01((sup_t + res_t) / 6)
    if width_pct < 3:
        width_fit = _clamp01(width_pct / 3 * 0.4)
    elif width_pct <= 12:
        width_fit = _clamp01(0.4 + (width_pct - 3) / 9 * 0.6)
    else:
        width_fit = _clamp01(1 - (width_pct - 12) / 18)
    liquidity_ok = dollar_vol > 2_000_000
    range_score = round(100 * (0.4 * flatness + 0.3 * tested + 0.3 * width_fit)
                        * (1 if liquidity_ok else 0.7))

    broke_up = price > range_high
    broke_down = price < range_low
    coil = _clamp01(1 - width_pct / 25)
    near_top = _clamp01((pos_raw - 0.5) / 0.5)
    vol_exp = _clamp01((vol_ratio - 1) / 1.5)
    breakout_score = round(100 * (0.35 * coil + 0.35 * near_top + 0.30 * vol_exp))
    if broke_up and vol_ratio > 1.3:
        breakout_score = min(100, breakout_score + 12)

    chg_pct = ((price - prev_close) / prev_close) * 100

    return Metrics(
        range_high=range_high, range_low=range_low, mid=mid, price=price,
        prev_close=prev_close, chg_pct=chg_pct, pos=pos, pos_raw=pos_raw,
        width_pct=width_pct, atr=atr, atr_pct=atr_pct, avg_vol=avg_vol,
        cur_vol=cur_vol, vol_ratio=vol_ratio, dollar_vol=dollar_vol,
        trend_pct_per_day=trend_pct_per_day, support_touches=sup_t,
        resistance_touches=res_t, flatness=flatness, liquidity_ok=liquidity_ok,
        range_score=range_score, broke_up=broke_up, broke_down=broke_down,
        breakout_score=breakout_score,
    )


def signal(m: Metrics, mode: str) -> Signal:
    """Turn metrics into an actionable signal with concrete price levels."""
    r2 = lambda x: round(x, 2)
    if mode == "range":
        stop = r2(m.range_low * 0.98)
        if m.pos <= 0.25 and m.flatness > 0.35 and m.liquidity_ok and not m.broke_down:
            return Signal("BUY", "price at the floor of a clean range",
                          entry_low=r2(m.range_low),
                          entry_high=r2(m.range_low + 0.25 * (m.range_high - m.range_low)),
                          target=r2(m.range_high), stop=stop)
        if m.pos >= 0.75 or m.broke_up:
            return Signal("EXIT", "at/above the ceiling — take profits, no new longs",
                          target=r2(m.range_high), stop=stop)
        return Signal("WAIT", "mid-range, no edge yet", target=r2(m.range_high), stop=stop)

    elif mode == "breakout":
        if m.broke_up and m.vol_ratio >= 1.3:
            return Signal("BUY", "closed above range high on heavy volume",
                          entry_low=r2(m.range_high), entry_high=r2(m.price),
                          target=r2(m.price + (m.range_high - m.range_low)),
                          stop=r2(m.range_high * 0.98))
        if m.broke_down and m.vol_ratio >= 1.3:
            return Signal("BREAKDOWN", "broke support on volume — stand aside / exit",
                          stop=r2(m.range_low))
        return Signal("WATCH", "coiling under resistance — waiting for a breakout",
                      entry_low=r2(m.range_high), entry_high=r2(m.range_high * 1.01),
                      target=r2(m.range_high + (m.range_high - m.range_low)),
                      stop=r2(m.range_low))

    raise ValueError(f"unknown mode: {mode!r}")


def score_for(m: Metrics, mode: str) -> int:
    return m.range_score if mode == "range" else m.breakout_score
