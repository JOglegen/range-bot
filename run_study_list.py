"""
Run a focused study-list scan for symbols from GitHub issues or manual review.

The default list comes from issue #5: TECL, ERX, EIX. This scan is alert-only;
it publishes JSON for the portal and can send the same Twilio summary format as
the main range scan.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys


DEFAULT_STUDY_SYMBOLS = ["TECL", "ERX", "EIX"]


def _parse_symbols(value: str) -> list[str]:
    symbols = [s.strip().upper() for s in value.replace("\n", ",").split(",")]
    return [s for s in symbols if s]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Focused RangeBot study-list scan")
    parser.add_argument("--symbols", default=",".join(DEFAULT_STUDY_SYMBOLS))
    parser.add_argument("--mode", default="range", choices=["range", "breakout"])
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--min-score", type=int, default=1, dest="min_score")
    parser.add_argument("--dry-run", action="store_true", help="Print SMS, don't send")
    parser.add_argument("--output", default="study_results.json")
    args = parser.parse_args(argv)

    from notify import notify_signals
    from screener import screen, top_buys, top_watches

    now = datetime.datetime.now()
    symbols = _parse_symbols(args.symbols)
    print(f"RangeBot study list: {', '.join(symbols)}")
    setups = screen(symbols, mode=args.mode, min_score=args.min_score, batch_size=20)
    buys = top_buys(setups, n=args.top)
    watches = top_watches(setups, n=args.top)

    payload = {
        "scanned_at": now.isoformat(),
        "mode": args.mode,
        "source": "GitHub issue #5 study list",
        "symbols": symbols,
        "total_scanned": len(symbols),
        "total_qualifying": len(setups),
        "buys": [s.__dict__ for s in buys],
        "watches": [s.__dict__ for s in watches],
        "all_setups": [s.__dict__ for s in setups],
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Study results saved -> {args.output}")

    notify_signals(
        buys=buys,
        watches=watches,
        mode=args.mode,
        scan_time=now.strftime("%-I:%M%p").lower(),
        total_scanned=len(symbols),
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
