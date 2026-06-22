"""
Maintain a $1,000 paper challenge from the latest 20-day range scan.

This is a simulation ledger only. It does not call a broker or submit orders.
It buys fractional paper shares from screener BUY signals, exits at stop/target
or explicit EXIT/BREAKDOWN signals, and publishes progress toward doubling.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


STARTING_CASH = 1000.0
TARGET_EQUITY = 2000.0
BENCHMARK_SYMBOL = "SPY"


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _price_map(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    import yfinance as yf

    raw = yf.download(
        sorted(set(symbols)),
        period="3mo",
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    prices: dict[str, float] = {}
    for sym in sorted(set(symbols)):
        try:
            df = raw[sym] if len(set(symbols)) > 1 else raw
            close = df["Close"].dropna()
            if not close.empty:
                prices[sym] = round(float(close.iloc[-1]), 4)
        except Exception:
            continue
    return prices


def _ma20(symbols: list[str]) -> dict[str, float | None]:
    if not symbols:
        return {}
    import yfinance as yf

    raw = yf.download(
        sorted(set(symbols)),
        period="3mo",
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    values: dict[str, float | None] = {}
    for sym in sorted(set(symbols)):
        try:
            df = raw[sym] if len(set(symbols)) > 1 else raw
            close = df["Close"].dropna()
            values[sym] = round(float(close.tail(20).mean()), 4) if len(close) >= 20 else None
        except Exception:
            values[sym] = None
    return values


def _benchmark_state(
    state: dict[str, Any],
    prices: dict[str, float],
    starting_cash: float,
    benchmark_symbol: str = BENCHMARK_SYMBOL,
) -> dict[str, Any]:
    existing = state.get("benchmark") or {}
    price = prices.get(benchmark_symbol)
    start_price = existing.get("start_price") or price
    shares = existing.get("shares")
    if shares is None and start_price:
        shares = starting_cash / float(start_price)

    if price and shares:
        equity = float(shares) * float(price)
    else:
        equity = float(existing.get("equity") or starting_cash)

    return {
        "symbol": benchmark_symbol,
        "start_price": round(float(start_price), 4) if start_price else None,
        "last_price": round(float(price), 4) if price else existing.get("last_price"),
        "shares": round(float(shares), 6) if shares else None,
        "equity": round(equity, 2),
        "return_pct": round((equity / starting_cash - 1) * 100, 2),
        "method": f"Buy-and-hold {benchmark_symbol} from paper challenge start",
    }


def update_challenge(
    screener_path: Path,
    state_path: Path,
    output_path: Path,
    starting_cash: float = STARTING_CASH,
    target_equity: float = TARGET_EQUITY,
    max_positions: int = 4,
    max_position_pct: float = 0.25,
) -> dict[str, Any]:
    scan = _load_json(screener_path, {})
    state = _load_json(state_path, {
        "started_at": dt.datetime.utcnow().isoformat(),
        "starting_cash": starting_cash,
        "target_equity": target_equity,
        "cash": starting_cash,
        "positions": {},
        "trades": [],
    })

    now = dt.datetime.utcnow().isoformat()
    buys = scan.get("buys") or []
    watched = {s.get("symbol"): s for s in (scan.get("all_setups") or []) + buys if s.get("symbol")}
    held_symbols = list((state.get("positions") or {}).keys())
    buy_symbols = [str(s.get("symbol", "")).upper() for s in buys if s.get("symbol")]
    prices = _price_map(sorted(set(held_symbols + buy_symbols + [BENCHMARK_SYMBOL])))
    ma20 = _ma20(sorted(set(held_symbols + buy_symbols)))

    cash = float(state.get("cash") or 0)
    positions: dict[str, Any] = state.get("positions") or {}
    trades: list[dict[str, Any]] = state.get("trades") or []

    # Mark-to-market and exit positions first.
    for sym in list(positions.keys()):
        pos = positions[sym]
        price = prices.get(sym) or float(pos.get("last_price") or pos.get("entry_price") or 0)
        pos["last_price"] = price
        setup = watched.get(sym, {})
        should_exit = (
            setup.get("signal") in ("EXIT", "BREAKDOWN")
            or (pos.get("stop") and price <= float(pos["stop"]))
            or (pos.get("target") and price >= float(pos["target"]))
        )
        if should_exit and price > 0:
            qty = float(pos["qty"])
            proceeds = qty * price
            pnl = proceeds - qty * float(pos["entry_price"])
            cash += proceeds
            trades.append({
                "time": now,
                "symbol": sym,
                "side": "SELL",
                "qty": round(qty, 6),
                "price": round(price, 4),
                "value": round(proceeds, 2),
                "pnl": round(pnl, 2),
                "reason": setup.get("signal") or "stop/target",
            })
            del positions[sym]

    equity_before_entries = cash + sum(
        float(p["qty"]) * float(p.get("last_price") or p["entry_price"])
        for p in positions.values()
    )

    # Enter new BUY signals with fractional paper shares.
    for setup in buys:
        sym = str(setup.get("symbol", "")).upper()
        if not sym or sym in positions or len(positions) >= max_positions:
            continue
        price = prices.get(sym) or float(setup.get("price") or 0)
        stop = setup.get("stop")
        if price <= 0 or not stop or cash < 25:
            continue
        allocation = min(cash, equity_before_entries * max_position_pct)
        qty = allocation / price
        if qty <= 0:
            continue
        cash -= allocation
        positions[sym] = {
            "qty": round(qty, 6),
            "entry_price": round(price, 4),
            "last_price": round(price, 4),
            "stop": setup.get("stop"),
            "target": setup.get("target"),
            "entry_time": now,
            "ma20_at_entry": ma20.get(sym),
            "source": "20-day range BUY",
        }
        trades.append({
            "time": now,
            "symbol": sym,
            "side": "BUY",
            "qty": round(qty, 6),
            "price": round(price, 4),
            "value": round(allocation, 2),
            "pnl": 0,
            "reason": "20-day range BUY",
        })

    equity = cash + sum(
        float(p["qty"]) * float(p.get("last_price") or p["entry_price"])
        for p in positions.values()
    )
    benchmark = _benchmark_state(state, prices, starting_cash)
    benchmark_delta = equity - float(benchmark["equity"])
    payload = {
        "updated_at": now,
        "mode": "paper_challenge",
        "status": "OPEN",
        "starting_cash": round(float(state.get("starting_cash") or starting_cash), 2),
        "target_equity": round(target_equity, 2),
        "cash": round(cash, 2),
        "equity": round(equity, 2),
        "return_pct": round((equity / starting_cash - 1) * 100, 2),
        "progress_to_double_pct": round(min(100, max(0, (equity - starting_cash) / (target_equity - starting_cash) * 100)), 2),
        "benchmark": benchmark,
        "vs_benchmark": {
            "equity_delta": round(benchmark_delta, 2),
            "return_delta_pct": round((equity / starting_cash - 1) * 100 - float(benchmark["return_pct"]), 2),
            "leader": "RangeBot" if benchmark_delta > 0 else BENCHMARK_SYMBOL if benchmark_delta < 0 else "Tie",
        },
        "positions": positions,
        "trades": trades[-100:],
        "latest_scan_at": scan.get("scanned_at"),
        "rules": {
            "paper_only": True,
            "max_positions": max_positions,
            "max_position_pct": max_position_pct,
            "entry_source": "20-day range BUY signals",
            "exit_source": "stop, target, EXIT, or BREAKDOWN",
            "benchmark": f"$1,000 buy-and-hold {BENCHMARK_SYMBOL} from the same start",
        },
    }
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="$1,000 paper challenge ledger")
    parser.add_argument("--screener", default="screener_results.json")
    parser.add_argument("--state", default="paper_challenge_state.json")
    parser.add_argument("--output", default="paper_challenge.json")
    args = parser.parse_args(argv)
    payload = update_challenge(Path(args.screener), Path(args.state), Path(args.output))
    print(
        f"Paper challenge: equity ${payload['equity']:.2f} "
        f"({payload['return_pct']:+.2f}%) positions={len(payload['positions'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
