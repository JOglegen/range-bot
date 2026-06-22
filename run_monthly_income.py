"""
Run the monthly dividend income scanner and write portal-ready JSON.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys


def _build_sms(candidates, scan_time: str) -> str:
    lines = [f"RangeBot {scan_time} CT | MONTHLY INCOME"]
    if not candidates:
        lines.append("\nNo monthly dividend candidates passed filters.")
    else:
        lines.append(f"\nTop monthly dividend candidates ({len(candidates)} shown):")
        for c in candidates[:5]:
            lines.append(
                f"  {c.symbol} ${c.price:.2f} yld:{c.trailing_yield_pct:.2f}% "
                f"score:{c.score} div:${c.avg_monthly_dividend:.3f}/mo"
            )
    lines.append("\ngithub.com/JOglegen/range-bot")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Monthly dividend income scanner")
    parser.add_argument("--symbols", default="", help="Comma-separated override universe")
    parser.add_argument("--min-yield", type=float, default=4.0)
    parser.add_argument("--max-yield", type=float, default=15.0)
    parser.add_argument("--min-score", type=int, default=55)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", help="Print SMS, do not send")
    parser.add_argument("--output", default="monthly_income.json")
    args = parser.parse_args(argv)

    from monthly_dividend import DEFAULT_MONTHLY_UNIVERSE, scan_monthly_income

    now = dt.datetime.now()
    symbols = list(DEFAULT_MONTHLY_UNIVERSE)
    if args.symbols.strip():
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    print("=" * 56)
    print("  RangeBot Monthly Dividend Income Scanner")
    print(f"  Min yield: {args.min_yield:.1f}% | Max yield: {args.max_yield:.1f}%")
    print(f"  Min score: {args.min_score}")
    print("=" * 56)

    candidates = scan_monthly_income(
        symbols=symbols,
        min_yield=args.min_yield,
        max_yield=args.max_yield,
        min_score=args.min_score,
    )
    top = candidates[:args.top]

    print(f"\n{len(candidates)} candidates passed filters")
    for c in top:
        print(
            f"  {c.symbol:<6} ${c.price:<8.2f} yld:{c.trailing_yield_pct:>5.2f}% "
            f"score:{c.score:>3} paid:{c.months_paid_12m}/12  {c.note}"
        )

    payload = {
        "scanned_at": now.isoformat(),
        "min_yield": args.min_yield,
        "max_yield": args.max_yield,
        "min_score": args.min_score,
        "total_scanned": len(symbols),
        "total_qualifying": len(candidates),
        "top_candidates": [c.__dict__ for c in top],
        "all_candidates": [c.__dict__ for c in candidates],
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\nResults saved -> {args.output}")

    sms = _build_sms(top, now.strftime("%I:%M%p").lstrip("0").lower())
    print("\n" + "-" * 50)
    print("SMS PREVIEW:")
    print(sms)
    print("-" * 50)

    if args.dry_run:
        print("[monthly] Dry run - SMS not sent")
    else:
        from notify import send_sms
        send_sms(sms)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
