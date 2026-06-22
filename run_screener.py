"""
run_screener.py — S&P 500 daily scan with SMS notification.

Runs at 3:45 PM CT (8 minutes before close) via GitHub Actions.
Screens all ~500 S&P 500 stocks, ranks the best setups, sends an SMS
with the top BUY signals and any WATCH/EXIT alerts.

Usage:
  python run_screener.py                    # full run, sends SMS
  python run_screener.py --dry-run          # prints SMS but doesn't send
  python run_screener.py --mode breakout    # breakout mode (default: range)
  python run_screener.py --top 10           # show top 10 (default: 5)
"""

from __future__ import annotations
import argparse
import datetime
import json
import sys


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="S&P 500 range scanner with SMS")
    p.add_argument("--mode",    default="range", choices=["range", "breakout"])
    p.add_argument("--top",     type=int, default=5, help="BUY signals to include in SMS")
    p.add_argument("--min-score", type=int, default=55, dest="min_score")
    p.add_argument("--dry-run", action="store_true", help="Print SMS, don't send")
    p.add_argument("--output",  default="screener_results.json",
                   help="Save full results as JSON (for portal dashboard)")
    args = p.parse_args(argv)

    now = datetime.datetime.now()
    scan_time = now.strftime("%-I:%M%p").lower()

    print(f"{'═'*56}")
    print(f"  RangeBot S&P 500 Screener")
    print(f"  Mode: {args.mode.upper()}  |  Min score: {args.min_score}")
    print(f"  Time: {now.strftime('%Y-%m-%d %H:%M CT')}")
    print(f"{'═'*56}\n")

    # ── 1. Fetch tickers ─────────────────────────────────────────────────────
    from screener import get_sp500_tickers, screen, top_buys, top_watches
    print("Fetching S&P 500 tickers from Wikipedia…")
    tickers = get_sp500_tickers()
    print(f"  Got {len(tickers)} tickers.\n")

    # ── 2. Screen ─────────────────────────────────────────────────────────────
    print("Screening…")
    setups = screen(tickers, mode=args.mode, min_score=args.min_score)
    buys   = top_buys(setups, n=args.top)
    watches = top_watches(setups, n=3)

    # ── 3. Print results ──────────────────────────────────────────────────────
    print(f"\n{'─'*56}")
    print(f"  {len(setups)} setups ≥ score {args.min_score}")
    print(f"  {len(buys)} BUY signals | {len(watches)} WATCH/EXIT\n")

    if buys:
        print("TOP BUY SETUPS:")
        for s in buys:
            print(f"  {s.symbol:<6} ${s.price:<8.2f}  score:{s.score}  "
                  f"pos:{s.pos_pct:.0f}%  width:{s.width_pct:.1f}%  "
                  f"vol:{s.vol_ratio:.1f}x")
            if s.entry_low and s.target and s.stop:
                print(f"         entry:${s.entry_low:.2f}–${s.entry_high:.2f}"
                      f"  target:${s.target:.2f}  stop:${s.stop:.2f}")
    else:
        print("  No BUY signals today.")

    if watches:
        print("\nWATCH / EXIT:")
        for s in watches:
            print(f"  {s.symbol:<6} ${s.price:.2f}  {s.signal}  {s.note}")
    print(f"{'─'*56}\n")

    # ── 4. Save JSON for portal ───────────────────────────────────────────────
    results_json = {
        "scanned_at": now.isoformat(),
        "mode": args.mode,
        "total_scanned": len(tickers),
        "total_qualifying": len(setups),
        "buys":   [s.__dict__ for s in buys],
        "watches": [s.__dict__ for s in watches],
        "all_setups": [s.__dict__ for s in setups[:50]],  # top 50 for portal
    }
    with open(args.output, "w") as f:
        json.dump(results_json, f, indent=2)
    print(f"Results saved → {args.output}")

    # ── 5. Send SMS ───────────────────────────────────────────────────────────
    from notify import notify_signals
    notify_signals(
        buys=buys,
        watches=watches,
        mode=args.mode,
        scan_time=scan_time,
        total_scanned=len(tickers),
        dry_run=args.dry_run,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
