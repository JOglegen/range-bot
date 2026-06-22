"""
Trade the current screener BUY list through the existing broker/risk pipeline.

This is intentionally paper-first. It reads the JSON produced by
run_screener.py, takes the top BUY symbols, then asks runner.py to recompute
fresh broker-side signals before any order is submitted. The JSON file chooses
the watchlist; the broker data still gets the final vote.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from config import load_settings
from runner import run_once


def _load_buy_symbols(path: Path, top: int) -> tuple[list[str], str, int]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    mode = data.get("mode", "range")
    buys = data.get("buys") or []
    symbols = []
    for setup in buys:
        sym = str(setup.get("symbol", "")).strip().upper()
        if sym and sym not in symbols:
            symbols.append(sym)
        if len(symbols) >= top:
            break
    return symbols, mode, int(data.get("total_scanned") or 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Paper-trade the latest RangeBot screener BUY signals"
    )
    parser.add_argument("--input", default="screener_results.json")
    parser.add_argument("--broker", default="alpaca_paper", choices=["alpaca_paper", "mock"])
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--min-score", type=int, default=55, dest="min_score")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")

    path = Path(args.input)
    if not path.exists():
        print(f"No screener file found: {path}")
        return 1

    symbols, mode, scanned = _load_buy_symbols(path, args.top)
    if not symbols:
        print(f"No BUY signals in {path} after scanning {scanned} symbols. Nothing to trade.")
        return 0

    settings = load_settings()
    settings.broker = args.broker
    settings.mode = mode
    settings.watchlist = symbols
    settings.min_score = args.min_score
    settings.validate()

    print("Trading screener BUY list through risk controls:")
    print(f"  broker : {settings.broker}")
    print(f"  mode   : {settings.mode}")
    print(f"  symbols: {', '.join(settings.watchlist)}")
    print(f"  dry run: {args.dry_run}")
    print(flush=True)

    run_once(settings, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
