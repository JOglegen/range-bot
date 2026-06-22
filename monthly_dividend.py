"""
Monthly dividend income scanner.

This scanner verifies monthly payment cadence from dividend history instead of
trusting a static list. It is for income watchlisting and alerts, not automatic
trading.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from statistics import mean
from typing import Iterable, List, Optional


DEFAULT_MONTHLY_UNIVERSE = [
    # Common monthly dividend stocks / REITs / BDCs
    "O", "ADC", "AGNC", "EPR", "LTC", "MAIN", "PSEC", "STAG", "SLG",
    "GOOD", "GLAD", "GAIN", "HRZN", "LAND", "OXSQ", "SCM", "ARR", "DX",
    "EFC", "ORC", "PFLT", "PNNT", "SBR", "SJT", "CRT", "PEO", "APLE",
    # Monthly income ETFs / funds often used by income investors
    "JEPI", "JEPQ", "DIVO", "SPHD", "PFF", "PFFD", "PEY", "DHS", "DTD",
    "DLN", "SPLV", "KBWY", "PGX", "HYG", "LQD", "BND", "VCIT", "VCLT",
    "SHV", "SGOV", "TFLO", "USFR", "TLT", "IEF",
]


@dataclass
class MonthlyIncomeCandidate:
    symbol: str
    price: float
    trailing_yield_pct: float
    annual_dividend: float
    avg_monthly_dividend: float
    payments_12m: int
    months_paid_12m: int
    dividend_growth_pct: Optional[float]
    price_vs_200dma_pct: Optional[float]
    drawdown_52w_pct: Optional[float]
    score: int
    note: str


def _distinct_payment_months(dividend_rows) -> int:
    return len({(idx.year, idx.month) for idx, value in dividend_rows.items() if value > 0})


def _pct_change(new: float, old: float) -> Optional[float]:
    if old <= 0:
        return None
    return (new / old - 1) * 100


def _score_candidate(
    yield_pct: float,
    months_paid: int,
    growth_pct: Optional[float],
    price_vs_200dma_pct: Optional[float],
    drawdown_52w_pct: Optional[float],
) -> tuple[int, str]:
    score = 0
    notes = []

    if 4 <= yield_pct <= 9:
        score += 35
        notes.append("healthy yield")
    elif 2 <= yield_pct < 4:
        score += 22
        notes.append("moderate yield")
    elif 9 < yield_pct <= 13:
        score += 22
        notes.append("high yield, watch risk")
    elif yield_pct > 13:
        score += 8
        notes.append("very high yield risk")

    if months_paid >= 12:
        score += 25
        notes.append("paid every month")
    elif months_paid >= 10:
        score += 15
        notes.append("mostly monthly")

    if growth_pct is not None:
        if growth_pct >= 5:
            score += 15
            notes.append("dividend rising")
        elif growth_pct >= -5:
            score += 8
            notes.append("dividend stable")
        else:
            notes.append("dividend shrinking")

    if price_vs_200dma_pct is not None:
        if price_vs_200dma_pct >= 0:
            score += 15
            notes.append("above 200dma")
        elif price_vs_200dma_pct >= -10:
            score += 7
            notes.append("near 200dma")
        else:
            notes.append("below 200dma")

    if drawdown_52w_pct is not None:
        if drawdown_52w_pct <= 15:
            score += 10
            notes.append("controlled drawdown")
        elif drawdown_52w_pct > 35:
            notes.append("large drawdown")

    return min(100, score), ", ".join(notes) or "income candidate"


def scan_monthly_income(
    symbols: Iterable[str] = DEFAULT_MONTHLY_UNIVERSE,
    min_yield: float = 4.0,
    max_yield: float = 15.0,
    min_score: int = 55,
    min_months_paid: int = 10,
) -> List[MonthlyIncomeCandidate]:
    """Return monthly dividend candidates ranked by income-quality score."""
    import yfinance as yf

    results: List[MonthlyIncomeCandidate] = []
    cutoff_12m = dt.date.today() - dt.timedelta(days=370)

    for raw_symbol in symbols:
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2y", actions=True, auto_adjust=False)
            if hist.empty or "Dividends" not in hist.columns:
                continue

            dividends = hist["Dividends"].dropna()
            dividends = dividends[dividends > 0]
            recent_divs = dividends[
                [idx.date() >= cutoff_12m for idx in dividends.index]
            ]
            if recent_divs.empty:
                continue

            months_paid = _distinct_payment_months(recent_divs)
            if months_paid < min_months_paid:
                continue

            price = float(hist["Close"].dropna().iloc[-1])
            annual_dividend = float(recent_divs.sum())
            yield_pct = annual_dividend / price * 100 if price > 0 else 0
            if yield_pct < min_yield or yield_pct > max_yield:
                continue

            last_six = recent_divs.tail(6).tolist()
            prior_six = recent_divs.iloc[max(0, len(recent_divs) - 12):max(0, len(recent_divs) - 6)].tolist()
            growth_pct = None
            if last_six and prior_six:
                growth_pct = _pct_change(mean(last_six), mean(prior_six))

            closes = hist["Close"].dropna()
            price_vs_200dma = None
            if len(closes) >= 200:
                sma200 = float(closes.tail(200).mean())
                price_vs_200dma = _pct_change(price, sma200)

            drawdown = None
            if len(closes) >= 20:
                high_52w = float(closes.tail(252).max())
                if high_52w > 0:
                    drawdown = (high_52w - price) / high_52w * 100

            score, note = _score_candidate(
                yield_pct=yield_pct,
                months_paid=months_paid,
                growth_pct=growth_pct,
                price_vs_200dma_pct=price_vs_200dma,
                drawdown_52w_pct=drawdown,
            )
            if score < min_score:
                continue

            results.append(MonthlyIncomeCandidate(
                symbol=symbol,
                price=round(price, 2),
                trailing_yield_pct=round(yield_pct, 2),
                annual_dividend=round(annual_dividend, 4),
                avg_monthly_dividend=round(annual_dividend / max(months_paid, 1), 4),
                payments_12m=int(len(recent_divs)),
                months_paid_12m=months_paid,
                dividend_growth_pct=round(growth_pct, 2) if growth_pct is not None else None,
                price_vs_200dma_pct=round(price_vs_200dma, 2) if price_vs_200dma is not None else None,
                drawdown_52w_pct=round(drawdown, 2) if drawdown is not None else None,
                score=score,
                note=note,
            ))
        except Exception as exc:
            print(f"[monthly] {symbol}: skipped ({exc})")

    results.sort(key=lambda c: (-c.score, -c.trailing_yield_pct))
    return results
