"""
screener.py — S&P 500 universe scanner.

Fetches the current S&P 500 constituent list from Wikipedia, downloads
90 days of daily bars for every ticker (batched via yfinance), runs the
20-day range scoring on each, and returns a ranked list of setups.

Designed to run ~5 minutes before market close on GitHub Actions so the
SMS hits your phone before the session ends.
"""

from __future__ import annotations
import datetime as dt
import sys
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from strategy import Bar, compute_metrics, signal as get_signal, score_for


@dataclass
class Setup:
    symbol:     str
    price:      float
    signal:     str   # BUY | WATCH | WAIT | EXIT | BREAKDOWN
    score:      int
    pos_pct:    float
    width_pct:  float
    vol_ratio:  float
    stop:       Optional[float]
    target:     Optional[float]
    entry_low:  Optional[float]
    entry_high: Optional[float]
    note:       str


_PRIORITY = {"BUY": 0, "WATCH": 1, "WAIT": 2, "EXIT": 3, "BREAKDOWN": 4}


def get_sp500_tickers() -> List[str]:
    """Fetch live S&P 500 constituents from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        df = pd.read_html(url, attrs={"id": "constituents"})[0]
    except Exception:
        df = pd.read_html(url)[0]
    tickers = df["Symbol"].tolist()
    # yfinance uses hyphens; Wikipedia uses dots for BRK.B etc.
    return sorted(t.replace(".", "-") for t in tickers)


def screen(
    tickers: List[str],
    mode:        str = "range",
    lookback:    int = 20,
    min_score:   int = 55,
    batch_size:  int = 100,
    start:       Optional[str] = None,
) -> List[Setup]:
    """
    Download bars for all tickers in batches, score each one, return setups
    at or above min_score, sorted by signal priority then score descending.
    """
    import yfinance as yf

    if start is None:
        start = (dt.date.today() - dt.timedelta(days=100)).isoformat()

    results: List[Setup] = []
    total = len(tickers)

    for batch_start in range(0, total, batch_size):
        batch = tickers[batch_start: batch_start + batch_size]
        pct = int((batch_start / total) * 100)
        print(f"  Screening {batch_start+1}–{min(batch_start+batch_size,total)}"
              f" of {total} ({pct}%)…", flush=True)

        try:
            raw = yf.download(
                batch, start=start, auto_adjust=True,
                progress=False, threads=True, group_by="ticker",
            )
        except Exception as e:
            print(f"    batch download error: {e}")
            continue

        for sym in batch:
            try:
                df = (raw[sym] if len(batch) > 1 else raw).dropna()
                if len(df) < lookback + 10:
                    continue

                bars = [
                    Bar(h=float(r["High"]), l=float(r["Low"]),
                        c=float(r["Close"]), v=float(r["Volume"]))
                    for _, r in df.iterrows()
                ]
                m = compute_metrics(bars, lookback=lookback)
                if m is None or not m.liquidity_ok:
                    continue

                sig = get_signal(m, mode)
                sc  = score_for(m, mode)
                if sc < min_score:
                    continue

                results.append(Setup(
                    symbol    = sym,
                    price     = round(m.price, 2),
                    signal    = sig.tag,
                    score     = sc,
                    pos_pct   = round(m.pos * 100, 1),
                    width_pct = round(m.width_pct, 1),
                    vol_ratio = round(m.vol_ratio, 2),
                    stop      = sig.stop,
                    target    = sig.target,
                    entry_low = sig.entry_low,
                    entry_high= sig.entry_high,
                    note      = sig.note,
                ))
            except Exception:
                continue

    results.sort(key=lambda s: (_PRIORITY.get(s.signal, 9), -s.score))
    return results


def top_buys(setups: List[Setup], n: int = 5) -> List[Setup]:
    return [s for s in setups if s.signal == "BUY"][:n]


def top_watches(setups: List[Setup], n: int = 3) -> List[Setup]:
    return [s for s in setups if s.signal in ("WATCH", "BREAKDOWN")][:n]


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "range"
    print(f"Fetching S&P 500 tickers…")
    tickers = get_sp500_tickers()
    print(f"Got {len(tickers)} tickers. Screening in {mode} mode…\n")
    setups = screen(tickers, mode=mode)
    buys   = top_buys(setups)
    print(f"\nTop BUY setups ({mode} mode):")
    for s in buys:
        print(f"  {s.symbol:<6} ${s.price:<8.2f} score:{s.score}  "
              f"pos:{s.pos_pct:.0f}%  entry:${s.entry_low or 0:.2f}–${s.entry_high or 0:.2f}"
              f"  tgt:${s.target or 0:.2f}  stop:${s.stop or 0:.2f}")
    print(f"\nTotal qualifying setups: {len(setups)}")
