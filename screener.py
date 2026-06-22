"""
screener.py — S&P 500 universe scanner.

Fetches the current S&P 500 constituent list from Wikipedia (with a
hardcoded fallback so Wikipedia outages can't break the scan), downloads
90 days of daily bars for every ticker via yfinance, runs the 20-day
range scoring on each, and returns a ranked list of setups.
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
    signal:     str
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

# Top 100 most liquid S&P 500 names — used if Wikipedia is unreachable
_FALLBACK = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","BRK-B","AVGO","JPM",
    "LLY","UNH","V","XOM","COST","MA","HD","PG","JNJ","ABBV","MRK","BAC",
    "NFLX","CRM","CVX","KO","AMD","WMT","PEP","TMO","MCD","CSCO","ACN","ABT",
    "ADBE","TXN","LIN","DHR","NKE","PM","NEE","INTC","ORCL","QCOM","UPS","MS",
    "GS","AMGN","IBM","HON","RTX","T","INTU","LOW","GE","SPGI","AXP","BKNG",
    "CAT","NOW","SYK","PLD","AMAT","MDLZ","VRTX","TJX","C","DE","BLK","REGN",
    "ADI","PANW","ISRG","MMC","ETN","PGR","CB","SBUX","GILD","LRCX","ADP",
    "ZTS","CME","MO","TMUS","SLB","CVS","EOG","APD","ITW","CL","PH","FDX",
    "NSC","WM","MCK","EMR","HCA","DUK","SO","ELV","CI","HUM","AON","AMGN",
]


def get_sp500_tickers() -> List[str]:
    """Fetch S&P 500 tickers from Wikipedia; fall back to hardcoded list."""
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        for df in tables:
            cols = [str(c).strip() for c in df.columns]
            sym_col = next((c for c in cols if "symbol" in c.lower()), None)
            if sym_col:
                tickers = [str(t).replace(".", "-").strip()
                           for t in df[sym_col].tolist()
                           if str(t) not in ("nan", "Symbol")]
                if len(tickers) > 400:
                    print(f"  Wikipedia: {len(tickers)} tickers")
                    return sorted(set(tickers))
        raise ValueError("no symbol column found")
    except Exception as e:
        print(f"  Wikipedia failed ({e}) — using {len(_FALLBACK)}-ticker fallback")
        return sorted(set(_FALLBACK))


def screen(
    tickers:   List[str],
    mode:      str = "range",
    lookback:  int = 20,
    min_score: int = 55,
    batch_size: int = 100,
    start:     Optional[str] = None,
) -> List[Setup]:
    """Download bars for all tickers in batches, score each, return ranked setups."""
    import yfinance as yf

    if start is None:
        start = (dt.date.today() - dt.timedelta(days=100)).isoformat()

    results: List[Setup] = []
    total = len(tickers)

    for i in range(0, total, batch_size):
        batch = tickers[i: i + batch_size]
        print(f"  {i+1}–{min(i+batch_size,total)}/{total}…", flush=True)
        try:
            raw = yf.download(
                batch, start=start, auto_adjust=True,
                progress=False, threads=True, group_by="ticker",
            )
        except Exception as e:
            print(f"    batch error: {e}")
            continue

        for sym in batch:
            try:
                df = (raw[sym] if len(batch) > 1 else raw).dropna()
                if len(df) < lookback + 10:
                    continue
                bars = [Bar(h=float(r["High"]), l=float(r["Low"]),
                            c=float(r["Close"]), v=float(r["Volume"]))
                        for _, r in df.iterrows()]
                m = compute_metrics(bars, lookback=lookback)
                if not m or not m.liquidity_ok:
                    continue
                sig = get_signal(m, mode)
                sc  = score_for(m, mode)
                if sc < min_score:
                    continue
                results.append(Setup(
                    symbol=sym, price=round(m.price,2), signal=sig.tag,
                    score=sc, pos_pct=round(m.pos*100,1),
                    width_pct=round(m.width_pct,1), vol_ratio=round(m.vol_ratio,2),
                    stop=sig.stop, target=sig.target,
                    entry_low=sig.entry_low, entry_high=sig.entry_high,
                    note=sig.note,
                ))
            except Exception:
                continue

    results.sort(key=lambda s: (_PRIORITY.get(s.signal, 9), -s.score))
    return results


def top_buys(setups: List[Setup], n: int = 5)   -> List[Setup]:
    return [s for s in setups if s.signal == "BUY"][:n]

def top_watches(setups: List[Setup], n: int = 3) -> List[Setup]:
    return [s for s in setups if s.signal in ("WATCH","BREAKDOWN")][:n]


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "range"
    print("Fetching tickers…")
    tickers = get_sp500_tickers()
    print(f"Screening {len(tickers)} tickers in {mode} mode…\n")
    setups = screen(tickers, mode=mode)
    for s in top_buys(setups):
        print(f"  {s.symbol:<6} ${s.price:<8.2f} score:{s.score}  "
              f"entry:${s.entry_low or 0:.2f}–${s.entry_high or 0:.2f}  "
              f"tgt:${s.target or 0:.2f}  stop:${s.stop or 0:.2f}")
