"""
run_command_center.py — the Ogle Command Center scan.

Runs the 13-model consensus engine across every asset class:
  Crypto     : BTC-USD, ETH-USD
  Stocks     : the range-bot watchlist
  ETFs       : SPY, QQQ
  Ag futures : Corn, Soybeans, Wheat, Live Cattle, Feeder Cattle

All data via yfinance (futures use CME front-month continuous tickers).
Output: portal/market_scores.json — consumed by the Command Center page.

The "score" is honest: it's derived from the actual model ballot
(buy votes minus sell votes, scaled to 0-100), and every vote is
included in the JSON so the dashboard can show WHY.
"""

from __future__ import annotations
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from command_center.models import Bar, run_all
from command_center.consensus import ConsensusEngine, ConsensusConfig

# ── asset universe ────────────────────────────────────────────────────────────

ASSETS = {
    # display name        yfinance ticker   category
    "Bitcoin":          ("BTC-USD",  "crypto"),
    "Ethereum":         ("ETH-USD",  "crypto"),
    "S&P 500":          ("SPY",      "etf"),
    "Nasdaq 100":       ("QQQ",      "etf"),
    "Apple":            ("AAPL",     "stock"),
    "Microsoft":        ("MSFT",     "stock"),
    "Nvidia":           ("NVDA",     "stock"),
    "AMD":              ("AMD",      "stock"),
    "JPMorgan":         ("JPM",      "stock"),
    "Exxon":            ("XOM",      "stock"),
    "Coca-Cola":        ("KO",       "stock"),
    "Walmart":          ("WMT",      "stock"),
    "Corn":             ("ZC=F",     "ag"),
    "Soybeans":         ("ZS=F",     "ag"),
    "Wheat":            ("ZW=F",     "ag"),
    "Live Cattle":      ("LE=F",     "ag"),
    "Feeder Cattle":    ("GF=F",     "ag"),
}


def fetch_bars(ticker: str, limit: int = 200):
    """Daily bars via yfinance. Returns list[Bar] or None on failure."""
    import yfinance as yf
    start = (datetime.date.today() - datetime.timedelta(days=limit + 40)).isoformat()
    try:
        df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
        df = df.dropna()
        if hasattr(df.columns, "levels"):   # flatten MultiIndex if present
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        if len(df) < 60:
            return None
        bars = [Bar(open=float(r["Open"]), high=float(r["High"]),
                    low=float(r["Low"]), close=float(r["Close"]),
                    volume=float(r["Volume"]) if r["Volume"] == r["Volume"] else 0.0)
                for _, r in df.iterrows()]
        return bars[-limit:]
    except Exception as e:
        print(f"    {ticker}: fetch failed ({e})")
        return None


def score_from_signal(sig) -> int:
    """
    Honest 0-100 score from the ballot.
    50 = neutral. Each net buy vote adds ~3.8 points; net sell subtracts.
    A perfect 13-0 buy sweep = 100; a 13-0 sell sweep = 0.
    """
    n = max(1, sig.buy_votes + sig.sell_votes + sig.hold_votes)
    return int(round(50 + (sig.score / n) * 50))


def main() -> int:
    print(f"\n{'═'*62}")
    print(f"  OGLE COMMAND CENTER — multi-asset consensus scan")
    print(f"  {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  |  13 models  |  {len(ASSETS)} assets")
    print(f"{'═'*62}\n")

    engine = ConsensusEngine(ConsensusConfig(buy_threshold=6, sell_threshold=6))
    results = []

    for name, (ticker, category) in ASSETS.items():
        print(f"  {name:<15} ({ticker})…", end=" ", flush=True)
        bars = fetch_bars(ticker)
        if not bars:
            print("no data — skipped")
            continue
        sig = engine.analyse(bars, symbol=ticker)
        score = score_from_signal(sig)
        print(f"score {score:>3}  {sig.direction:<4}  "
              f"[{sig.buy_votes}↑ {sig.sell_votes}↓ {sig.hold_votes}·]  "
              f"${sig.price:,.2f}")

        results.append({
            "name":       name,
            "ticker":     ticker,
            "category":   category,
            "score":      score,
            "direction":  sig.direction,
            "buy_votes":  sig.buy_votes,
            "sell_votes": sig.sell_votes,
            "hold_votes": sig.hold_votes,
            "confidence": sig.confidence,
            "kelly_size": sig.kelly_size,
            "price":      round(sig.price, 2),
            "votes": [
                {"model": v.model, "vote": v.vote, "value": v.value, "note": v.note}
                for v in sig.votes
            ],
        })

    # Rank: best opportunity = highest score with a BUY direction
    results.sort(key=lambda r: -r["score"])
    buys = [r for r in results if r["direction"] == "BUY"]
    best = buys[0] if buys else (results[0] if results else None)

    payload = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "model_count": 13,
        "asset_count": len(results),
        "best_opportunity": best["name"] if best else None,
        "assets": results,
    }

    out = Path(__file__).parent / "portal" / "market_scores.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"\n  {len(results)} assets scored → {out}")
    if best:
        print(f"  Best opportunity: {best['name']} (score {best['score']}, {best['direction']})")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
