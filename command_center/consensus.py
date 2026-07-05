"""
consensus.py — Vote aggregation, consensus scoring, and Kelly position sizing.

The edge isn't any single model being right. It's requiring that multiple
independent models agree before risking capital. One model is noise;
8+ out of 13 agreeing is signal.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from command_center.models import Bar, Vote, run_all


# ── configuration ─────────────────────────────────────────────────────────────

@dataclass
class ConsensusConfig:
    buy_threshold:  int   = 6    # need ≥ 6 BUY votes out of 13 to signal BUY
    sell_threshold: int   = 6    # need ≥ 6 SELL votes to signal SELL
    kelly_fraction: float = 0.25 # fractional Kelly cap (never risk more than 25%)
    half_kelly:     bool  = True  # use half-Kelly for safety (recommended)
    min_bars:       int   = 55   # minimum bars needed to run all models


# ── signal ────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    timestamp:   str
    symbol:      str
    direction:   str         # BUY | SELL | HOLD
    buy_votes:   int
    sell_votes:  int
    hold_votes:  int
    score:       int         # net: buy_votes - sell_votes
    confidence:  float       # score / total_models
    kelly_size:  float       # suggested position size as fraction of equity
    price:       float
    notes:       List[str]   = field(default_factory=list)
    votes:       List[Vote]  = field(default_factory=list)

    def summary(self) -> str:
        bar  = "█" * self.buy_votes + "░" * self.sell_votes + "·" * self.hold_votes
        conf = f"{self.confidence*100:+.0f}%"
        size = f"{self.kelly_size*100:.1f}%"
        return (f"{self.timestamp}  {self.symbol:<8}  {self.direction:<4}  "
                f"[{self.buy_votes}↑ {self.sell_votes}↓ {self.hold_votes}·]  "
                f"conf:{conf}  kelly:{size}  price:${self.price:,.2f}")


# ── engine ────────────────────────────────────────────────────────────────────

class ConsensusEngine:
    def __init__(self, config: ConsensusConfig = None):
        self.cfg = config or ConsensusConfig()

    def analyse(self, bars: List[Bar], symbol: str = "BTC-USD",
                win_rate: float = 0.52, avg_win: float = 0.04,
                avg_loss: float = 0.02) -> Signal:
        """
        Run all models against the bar history and produce a Signal.

        win_rate / avg_win / avg_loss are used for Kelly sizing.
        Defaults are conservative estimates — update from backtest results.
        """
        if len(bars) < self.cfg.min_bars:
            ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            return Signal(ts, symbol, "HOLD", 0, 0, 0, 0, 0.0, 0.0, bars[-1].close,
                          [f"Need {self.cfg.min_bars} bars, have {len(bars)}"])

        votes    = run_all(bars)
        buys     = sum(1 for v in votes if v.vote == 1)
        sells    = sum(1 for v in votes if v.vote == -1)
        holds    = sum(1 for v in votes if v.vote == 0)
        n        = len(votes)
        score    = buys - sells
        conf     = score / n

        if buys >= self.cfg.buy_threshold:
            direction = "BUY"
        elif sells >= self.cfg.sell_threshold:
            direction = "SELL"
        else:
            direction = "HOLD"

        kelly = self._kelly(win_rate, avg_win, avg_loss)
        # Scale Kelly by confidence: stronger consensus = larger size
        kelly_adjusted = kelly * min(1.0, abs(conf) * 2) if direction != "HOLD" else 0.0

        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        notes = [v.note for v in votes if v.vote != 0]

        return Signal(
            timestamp  = ts,
            symbol     = symbol,
            direction  = direction,
            buy_votes  = buys,
            sell_votes = sells,
            hold_votes = holds,
            score      = score,
            confidence = round(conf, 3),
            kelly_size = round(min(kelly_adjusted, self.cfg.kelly_fraction), 4),
            price      = bars[-1].close,
            notes      = notes,
            votes      = votes,
        )

    def _kelly(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """
        Kelly criterion: f* = (win_rate / avg_loss) - (loss_rate / avg_win)
        Returns half-Kelly if configured (strongly recommended).
        """
        loss_rate = 1 - win_rate
        if avg_win <= 0 or avg_loss <= 0:
            return 0.0
        f = (win_rate / avg_loss) - (loss_rate / avg_win)
        f = max(0.0, min(f, self.cfg.kelly_fraction))
        return f * 0.5 if self.cfg.half_kelly else f

    def print_ballot(self, signal: Signal) -> None:
        """Print a detailed vote breakdown to the console."""
        print(f"\n{'═'*60}")
        print(f"  {signal.symbol}  |  ${signal.price:,.2f}  |  {signal.timestamp}")
        print(f"{'═'*60}")
        print(f"  {'MODEL':<18} {'VOTE':^6} {'VALUE':>10}  NOTE")
        print(f"  {'─'*58}")
        for v in signal.votes:
            icon = "🟢" if v.vote == 1 else "🔴" if v.vote == -1 else "⬜"
            lbl  = "BUY " if v.vote == 1 else "SELL" if v.vote == -1 else "HOLD"
            print(f"  {v.model:<18} {icon} {lbl}  {v.value:>8}  {v.note}")
        print(f"  {'─'*58}")
        print(f"  Votes: {signal.buy_votes}↑ BUY  {signal.sell_votes}↓ SELL  {signal.hold_votes}· HOLD")
        print(f"  Score: {signal.score:+d} / {len(signal.votes)}  Confidence: {signal.confidence*100:+.0f}%")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        colour = "🟢 BUY " if signal.direction == "BUY" else "🔴 SELL" if signal.direction == "SELL" else "⬜ HOLD"
        print(f"  SIGNAL: {colour}  |  Kelly size: {signal.kelly_size*100:.1f}% of equity")
        print(f"{'═'*60}\n")
