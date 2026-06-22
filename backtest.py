"""
Backtesting engine for the 20-day range strategy.

Execution model (realistic, no look-ahead):
  Signal fires at today's CLOSE (bar i).
  → Entry fills at bar i+1 OPEN + slippage.
  During every held bar:
    · If LOW <= stop  → stopped out at stop price  (pessimistic: checked first).
    · If HIGH >= target → take-profit at target price.
    · If EXIT signal  → close at next bar's open.
    · If max-hold bars elapsed → close at close.
  Commissions: $0 (Alpaca / Schwab are commission-free).
  Slippage: 0.10% per fill (bid-ask on liquid names).

Portfolio simulation:
  All symbols are simulated chronologically on a shared calendar so that
  capital is shared, the position cap is enforced across the whole portfolio,
  and the equity curve is correct.

Walk-forward:
  Split history at `split_date`. Sweep parameters on the IN-SAMPLE half,
  report honestly on the OUT-OF-SAMPLE half.

Monte Carlo:
  Bootstrap-resamples (with replacement) the trade P&L series 2000 times,
  giving a genuine distribution of outcomes. Total P&L varies across sims
  because different trades are drawn (some more than once, some not at all).
"""

from __future__ import annotations

import collections
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from data import OHLCVBar, load_data
from strategy import Bar, compute_metrics, signal as get_signal, score_for

SLIPPAGE = 0.001   # 0.10% per fill


# ─── data structures ──────────────────────────────────────────────────────────

@dataclass
class Trade:
    symbol:      str
    entry_date:  date
    exit_date:   date
    entry_price: float
    exit_price:  float
    qty:         int
    exit_reason: str   # stop | target | signal | timeout
    mode:        str

    @property
    def pl_pct(self) -> float:
        return (self.exit_price - self.entry_price) / self.entry_price

    @property
    def pl_dollars(self) -> float:
        return (self.exit_price - self.entry_price) * self.qty

    @property
    def hold_days(self) -> int:
        return max(1, (self.exit_date - self.entry_date).days)


@dataclass
class EquityPoint:
    date:   date
    equity: float


@dataclass
class BacktestResult:
    trades:       List[Trade]
    equity_curve: List[EquityPoint]
    start_equity: float
    settings_used: dict

    # ── metrics ────────────────────────────────────────────────────────────

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1].equity if self.equity_curve else self.start_equity

    @property
    def total_return_pct(self) -> float:
        return (self.final_equity / self.start_equity - 1) * 100

    @property
    def cagr(self) -> float:
        if not self.equity_curve or len(self.equity_curve) < 2:
            return 0.0
        days = (self.equity_curve[-1].date - self.equity_curve[0].date).days
        years = max(days / 365.25, 0.01)
        ratio = self.final_equity / max(self.start_equity, 0.01)
        return ((max(ratio, 1e-6) ** (1 / years)) - 1) * 100

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.pl_pct > 0) / len(self.trades) * 100

    @property
    def avg_win_pct(self) -> float:
        wins = [t.pl_pct for t in self.trades if t.pl_pct > 0]
        return (sum(wins) / len(wins) * 100) if wins else 0.0

    @property
    def avg_loss_pct(self) -> float:
        losses = [t.pl_pct for t in self.trades if t.pl_pct <= 0]
        return (sum(losses) / len(losses) * 100) if losses else 0.0

    @property
    def profit_factor(self) -> float:
        gw = sum(t.pl_dollars for t in self.trades if t.pl_dollars > 0)
        gl = abs(sum(t.pl_dollars for t in self.trades if t.pl_dollars < 0))
        return gw / gl if gl > 0 else float("inf")

    @property
    def expectancy_pct(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.pl_pct for t in self.trades) / len(self.trades) * 100

    @property
    def max_drawdown_pct(self) -> float:
        peak = self.start_equity
        max_dd = 0.0
        for pt in self.equity_curve:
            peak = max(peak, pt.equity)
            dd = (peak - pt.equity) / peak
            max_dd = max(max_dd, dd)
        return max_dd * 100

    def _daily_returns(self) -> List[float]:
        equities = [pt.equity for pt in self.equity_curve]
        return [(equities[i] - equities[i - 1]) / equities[i - 1]
                for i in range(1, len(equities))]

    @property
    def sharpe(self) -> float:
        rets = self._daily_returns()
        if len(rets) < 30:
            return 0.0
        mu  = sum(rets) / len(rets)
        std = (sum((r - mu) ** 2 for r in rets) / len(rets)) ** 0.5
        return (mu / std * math.sqrt(252)) if std > 0 else 0.0

    @property
    def sortino(self) -> float:
        rets = self._daily_returns()
        if len(rets) < 30:
            return 0.0
        mu  = sum(rets) / len(rets)
        neg = [r for r in rets if r < 0]
        if not neg:
            return 999.0
        dstd = (sum(r ** 2 for r in neg) / len(neg)) ** 0.5
        return (mu / dstd * math.sqrt(252)) if dstd > 0 else 0.0

    @property
    def calmar(self) -> float:
        return self.cagr / self.max_drawdown_pct if self.max_drawdown_pct > 0 else 0.0

    @property
    def avg_hold_days(self) -> float:
        return (sum(t.hold_days for t in self.trades) / len(self.trades)
                if self.trades else 0.0)

    def monthly_returns(self) -> Dict[Tuple[int, int], float]:
        monthly: Dict[Tuple[int, int], List[EquityPoint]] = collections.defaultdict(list)
        for pt in self.equity_curve:
            monthly[(pt.date.year, pt.date.month)].append(pt)
        result = {}
        for (y, m), pts in monthly.items():
            pts.sort(key=lambda p: p.date)
            if pts[0].equity > 0:
                result[(y, m)] = (pts[-1].equity / pts[0].equity - 1) * 100
        return result

    def symbol_breakdown(self) -> Dict[str, dict]:
        by_sym: Dict[str, List[Trade]] = collections.defaultdict(list)
        for t in self.trades:
            by_sym[t.symbol].append(t)
        out = {}
        for sym, trades in by_sym.items():
            wins = [t for t in trades if t.pl_pct > 0]
            out[sym] = {
                "trades":    len(trades),
                "win_rate":  len(wins) / len(trades) * 100,
                "avg_pl_pct": sum(t.pl_pct for t in trades) / len(trades) * 100,
                "total_pl":  sum(t.pl_dollars for t in trades),
            }
        return out

    def exit_breakdown(self) -> Dict[str, int]:
        d: Dict[str, int] = {}
        for t in self.trades:
            d[t.exit_reason] = d.get(t.exit_reason, 0) + 1
        return d


# ─── position (internal) ─────────────────────────────────────────────────────

@dataclass
class _Pos:
    symbol:        str
    entry_date:    date
    entry_price:   float
    stop:          float
    target:        float
    qty:           int
    entry_bar_idx: int   # index in that symbol's bar list


# ─── portfolio-level chronological simulator ──────────────────────────────────

def _size_position(equity: float, entry: float, stop: float,
                   risk_pct: float, max_pos_pct: float) -> int:
    per_share_risk = entry - stop
    if per_share_risk <= 0 or entry <= 0:
        return 0
    qty_risk  = math.floor(equity * risk_pct / per_share_risk)
    qty_val   = math.floor(equity * max_pos_pct / entry)
    qty_cash  = math.floor(equity / entry)
    return max(0, min(qty_risk, qty_val, qty_cash))


def run_portfolio(
    data: Dict[str, List[OHLCVBar]],
    mode:            str   = "range",
    lookback:        int   = 20,
    min_score:       int   = 60,
    risk_pct:        float = 0.01,
    max_pos_pct:     float = 0.25,
    max_positions:   int   = 4,
    max_hold:        int   = 20,
    start_equity:    float = 10_000.0,
) -> BacktestResult:
    """
    Simulate the strategy across all symbols on a shared timeline.

    At each market date (in calendar order):
      1. Process stop / target / timeout exits for every held position.
      2. For symbols with an EXIT/BREAKDOWN signal, close at today's open.
      3. For non-held symbols, compute signal. Queue BUY entries (best score).
      4. Open queued entries using today's open price.
    """
    # Build an index of {date: {symbol: bar_index}} for fast daily lookup.
    sym_bars: Dict[str, List[OHLCVBar]] = {
        s: b for s, b in data.items() if len(b) >= lookback + 10
    }
    if not sym_bars:
        return BacktestResult([], [], start_equity, {})

    # Map: symbol → date → bar index (for quick signal computation)
    date_idx: Dict[str, Dict[date, int]] = {
        sym: {bars[i].date: i for i in range(len(bars))}
        for sym, bars in sym_bars.items()
    }

    # All unique dates sorted
    all_dates = sorted({b.date for bars in sym_bars.values() for b in bars})

    equity = start_equity
    positions: Dict[str, _Pos] = {}         # symbol → _Pos
    trades:    List[Trade]     = []
    curve:     List[EquityPoint] = []
    pending:   Dict[str, Tuple[float, float, int]] = {}  # symbol → (stop, tgt, score)

    for today_date in all_dates:
        # ─── 1. Exits during today's bar ────────────────────────────────────
        for sym in list(positions.keys()):
            p = positions[sym]
            idx = date_idx[sym].get(today_date)
            if idx is None:
                continue
            bar = sym_bars[sym][idx]
            hold = idx - p.entry_bar_idx

            exit_px = None
            reason = None
            if bar.l <= p.stop:
                exit_px = p.stop
                reason  = "stop"
            elif bar.h >= p.target:
                exit_px = p.target
                reason  = "target"
            elif hold >= max_hold:
                exit_px = bar.c
                reason  = "timeout"

            if exit_px is not None:
                fill = round(exit_px * (1 - SLIPPAGE), 4)
                trades.append(Trade(
                    symbol=sym, entry_date=p.entry_date, exit_date=today_date,
                    entry_price=p.entry_price, exit_price=fill, qty=p.qty,
                    exit_reason=reason, mode=mode,
                ))
                equity += fill * p.qty - p.entry_price * p.qty
                del positions[sym]

        # ─── 2. Fill entries queued from yesterday's signal ─────────────────
        filled_today = []
        for sym, (stop, tgt, sc) in list(pending.items()):
            if sym in positions:
                filled_today.append(sym)
                continue
            if len(positions) >= max_positions:
                break
            idx = date_idx[sym].get(today_date)
            if idx is None:
                filled_today.append(sym)
                continue
            bar   = sym_bars[sym][idx]
            entry = round(bar.o * (1 + SLIPPAGE), 4)
            qty   = _size_position(equity, entry, stop, risk_pct, max_pos_pct)
            if qty > 0:
                positions[sym] = _Pos(
                    symbol=sym, entry_date=today_date,
                    entry_price=entry, stop=stop, target=tgt,
                    qty=qty, entry_bar_idx=idx,
                )
            filled_today.append(sym)
        for sym in filled_today:
            pending.pop(sym, None)

        # ─── 3. Compute signals for today → queue for tomorrow ──────────────
        candidates: List[Tuple[int, str, float, float]] = []  # (score, sym, stop, tgt)

        for sym, bars in sym_bars.items():
            idx = date_idx[sym].get(today_date)
            if idx is None or idx < lookback + 2:
                continue
            history = [b.as_bar() for b in bars[: idx + 1]]
            m = compute_metrics(history, lookback=lookback)
            if m is None:
                continue
            sig = get_signal(m, mode)
            sc  = score_for(m, mode)

            # Close signal on held position (at tomorrow's open).
            # RANGE mode:  EXIT only blocks NEW entries — existing bracket
            #              positions ride to stop/target/timeout as planned.
            # BREAKOUT mode: BREAKDOWN is a meaningful close signal.
            should_exit = (mode == "breakout" and sig.tag in ("EXIT", "BREAKDOWN"))
            if sym in positions and should_exit:
                p = positions[sym]
                next_idx = idx + 1
                if next_idx < len(bars):
                    nxt  = bars[next_idx]
                    fill = round(nxt.o * (1 - SLIPPAGE), 4)
                    trades.append(Trade(
                        symbol=sym, entry_date=p.entry_date,
                        exit_date=nxt.date, entry_price=p.entry_price,
                        exit_price=fill, qty=p.qty, exit_reason="signal",
                        mode=mode,
                    ))
                    equity += fill * p.qty - p.entry_price * p.qty
                    del positions[sym]

            # Entry candidate
            if sym not in positions and sig.tag == "BUY" and sc >= min_score:
                if sig.stop and sig.target and sig.stop < m.price < sig.target:
                    candidates.append((sc, sym, sig.stop, sig.target))

        # Sort by score desc; take only the best available slot(s)
        candidates.sort(reverse=True)
        for sc, sym, stop, tgt in candidates:
            if sym not in pending and sym not in positions:
                pending[sym] = (stop, tgt, sc)

        curve.append(EquityPoint(date=today_date, equity=round(equity, 2)))

    return BacktestResult(
        trades=sorted(trades, key=lambda t: t.exit_date),
        equity_curve=curve,
        start_equity=start_equity,
        settings_used={
            "mode": mode, "lookback": lookback, "min_score": min_score,
            "risk_pct": risk_pct, "symbols": list(sym_bars.keys()),
        },
    )


# ─── Backtester class (convenience wrapper) ──────────────────────────────────

class Backtester:
    def __init__(self, symbols: List[str], mode: str = "range", lookback: int = 20,
                 min_score: int = 60, risk_pct: float = 0.01,
                 max_pos_pct: float = 0.25, max_positions: int = 4,
                 start_equity: float = 10_000.0, offline: bool = False,
                 start: str = "2019-01-01",
                 data: Optional[Dict] = None):
        self.symbols = symbols
        self.kw = dict(mode=mode, lookback=lookback, min_score=min_score,
                       risk_pct=risk_pct, max_pos_pct=max_pos_pct,
                       max_positions=max_positions, start_equity=start_equity)
        self._data = data
        self.offline = offline
        self.start = start
        self.start_equity = start_equity

    def _load(self):
        if self._data:
            return self._data
        return load_data(self.symbols, start=self.start, offline=self.offline)

    def run(self, data=None) -> BacktestResult:
        return run_portfolio(data or self._load(), **self.kw)


# ─── walk-forward ─────────────────────────────────────────────────────────────

def walk_forward(symbols: List[str], mode: str, split_date: str,
                 offline: bool, start: str = "2019-01-01",
                 param_grid: Optional[dict] = None,
                 start_equity: float = 10_000.0) -> dict:
    split = date.fromisoformat(split_date)
    raw   = load_data(symbols, start=start, offline=offline)

    in_raw  = {s: [b for b in bars if b.date <  split] for s, bars in raw.items()}
    out_raw = {s: [b for b in bars if b.date >= split] for s, bars in raw.items()}

    grid = param_grid or {
        "lookback":  [15, 20, 25, 30],
        "min_score": [50, 60, 70],
    }

    best_sharpe  = -999.0
    best_params  = {"lookback": 20, "min_score": 60}
    sweep_rows   = []

    print("Walk-forward parameter sweep (in-sample):")
    for lb in grid["lookback"]:
        for ms in grid["min_score"]:
            res = run_portfolio(in_raw, mode=mode, lookback=lb,
                                min_score=ms, start_equity=start_equity)
            sh  = res.sharpe
            row = (lb, ms, sh, res.cagr, res.max_drawdown_pct, len(res.trades))
            sweep_rows.append(row)
            print(f"  lookback={lb:2d}  min_score={ms:2d}  "
                  f"sharpe={sh:+.2f}  cagr={res.cagr:+.1f}%  "
                  f"dd={res.max_drawdown_pct:.1f}%  n={len(res.trades)}")
            if sh > best_sharpe and len(res.trades) >= 5:
                best_sharpe = sh
                best_params = {"lookback": lb, "min_score": ms}

    print(f"\n  Best in-sample: {best_params}  (Sharpe {best_sharpe:+.2f})")

    in_res  = run_portfolio(in_raw,  mode=mode, start_equity=start_equity, **best_params)
    out_res = run_portfolio(out_raw, mode=mode, start_equity=start_equity, **best_params)
    print(f"  Out-of-sample:  CAGR {out_res.cagr:+.1f}%  "
          f"Sharpe {out_res.sharpe:+.2f}  MaxDD {out_res.max_drawdown_pct:.1f}%  "
          f"Trades {len(out_res.trades)}\n")

    return {"best_params": best_params, "in_sample": in_res,
            "out_of_sample": out_res, "sweep": sweep_rows}


# ─── Monte Carlo (bootstrap resampling) ──────────────────────────────────────

def monte_carlo(trades: List[Trade], start_equity: float,
                n_sims: int = 2_000, seed: int = 42) -> dict:
    """
    Bootstrap-resample (with replacement) trade P&L percentages.
    Each simulation draws n trades randomly, applies them to a running equity.
    Results vary because some trades appear multiple times, others not at all.
    """
    if len(trades) < 2:
        return {"curves": [], "pct5": [], "pct50": [], "pct95": [],
                "win_pct": 0.0, "final_mean": start_equity,
                "final_p5": start_equity, "final_p95": start_equity}

    rng = random.Random(seed)
    n   = len(trades)

    # Use pct P&L and approximate position sizing (25% of current equity).
    pl_pcts = [t.pl_pct for t in trades]

    all_finals: List[float] = []
    sampled_curves: List[List[float]] = []

    for sim in range(n_sims):
        sample   = [rng.choice(pl_pcts) for _ in range(n)]
        eq       = start_equity
        curve    = []
        pos_size = eq * 0.25            # approx allocation per trade
        for pct in sample:
            eq += pos_size * pct
            eq  = max(eq, 0.01)         # floor at near-zero
            pos_size = eq * 0.25        # update sizing with equity
            curve.append(eq)
        all_finals.append(eq)
        if sim < 300:
            sampled_curves.append(curve)

    arr = np.array(all_finals)
    win_pct = float(np.mean(arr > start_equity) * 100)

    # Percentile bands across stored curves
    target_len = min(len(c) for c in sampled_curves) if sampled_curves else 0
    trimmed    = [c[:target_len] for c in sampled_curves if len(c) >= target_len]
    if trimmed and target_len > 0:
        mat  = np.array(trimmed)
        p5   = np.percentile(mat, 5,  axis=0).tolist()
        p50  = np.percentile(mat, 50, axis=0).tolist()
        p95  = np.percentile(mat, 95, axis=0).tolist()
    else:
        p5 = p50 = p95 = []

    return {
        "curves": sampled_curves, "pct5": p5, "pct50": p50, "pct95": p95,
        "win_pct":     win_pct,
        "final_mean":  float(np.mean(arr)),
        "final_p5":    float(np.percentile(arr, 5)),
        "final_p95":   float(np.percentile(arr, 95)),
    }


# ─── parameter sensitivity grid ──────────────────────────────────────────────

def param_sensitivity(raw_data: dict, mode: str, symbols: List[str],
                      start_equity: float = 10_000.0) -> dict:
    lookbacks  = [10, 15, 20, 25, 30]
    min_scores = [40, 50, 60, 70, 80]
    grid = []
    for lb in lookbacks:
        row = []
        for ms in min_scores:
            res = run_portfolio(raw_data, mode=mode, lookback=lb,
                                min_score=ms, start_equity=start_equity)
            row.append(round(res.sharpe, 3))
        grid.append(row)
    return {"lookbacks": lookbacks, "min_scores": min_scores, "sharpe_grid": grid}
