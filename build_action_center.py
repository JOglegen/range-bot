"""
Build a portal-ready action center from the latest scanner JSON files.

This does not place trades. It turns the range and monthly-income scans into a
single ranked operational list for the dashboard.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _money(value: Any) -> str:
    if value is None:
        return "-"
    return f"${float(value):.2f}"


def _trade_rows(scan: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in (scan.get("buys") or [])[:limit]:
        entry_low = item.get("entry_low")
        entry_high = item.get("entry_high")
        entry = (
            f"{_money(entry_low)}-{_money(entry_high)}"
            if entry_low is not None and entry_high is not None
            else _money(entry_low)
        )
        stop = item.get("stop")
        price = item.get("price")
        stop_gap = None
        if stop and price:
            stop_gap = round((float(price) - float(stop)) / float(price) * 100, 1)
        rows.append({
            "type": "TRADE ENTRY",
            "symbol": item.get("symbol"),
            "priority": int(item.get("score") or 0),
            "action": "Review buy zone",
            "status": "Paper bot will recheck before any order",
            "detail": f"Entry {entry} | target {_money(item.get('target'))} | stop {_money(stop)}",
            "risk": f"{stop_gap}% to stop" if stop_gap is not None else "stop required",
            "source": "20-day range",
        })

    for item in (scan.get("watches") or [])[:3]:
        tag = item.get("signal") or "WATCH"
        rows.append({
            "type": "EXIT WATCH" if tag in ("EXIT", "BREAKDOWN") else "WATCH",
            "symbol": item.get("symbol"),
            "priority": int(item.get("score") or 0),
            "action": tag,
            "status": "Manual review",
            "detail": item.get("note") or "",
            "risk": f"pos {item.get('pos_pct')}%" if item.get("pos_pct") is not None else "",
            "source": "20-day range",
        })
    return rows


def _income_rows(income: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in (income.get("top_candidates") or [])[:limit]:
        score = int(item.get("score") or 0)
        yield_pct = item.get("trailing_yield_pct")
        drawdown = item.get("drawdown_52w_pct")
        rows.append({
            "type": "INCOME WATCH",
            "symbol": item.get("symbol"),
            "priority": score,
            "action": "Review for income list",
            "status": "Alert only, no auto-buy",
            "detail": (
                f"Yield {float(yield_pct):.2f}% | "
                f"avg/mo ${float(item.get('avg_monthly_dividend') or 0):.3f} | "
                f"paid {item.get('months_paid_12m')}/12 months"
            ),
            "risk": f"{float(drawdown):.1f}% 52w drawdown" if drawdown is not None else "drawdown n/a",
            "source": "monthly dividend",
        })
    return rows


def _study_rows(study: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    items = (study.get("buys") or []) + (study.get("watches") or []) + (study.get("all_setups") or [])
    seen: set[str] = set()
    for item in items:
        symbol = item.get("symbol")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        signal = item.get("signal") or "WATCH"
        rows.append({
            "type": "STUDY ENTRY" if signal == "BUY" else "STUDY WATCH",
            "symbol": symbol,
            "priority": int(item.get("score") or 0),
            "action": signal,
            "status": "Study list alert, manual review",
            "detail": item.get("note") or "",
            "risk": f"pos {item.get('pos_pct')}%" if item.get("pos_pct") is not None else "",
            "source": study.get("source") or "study list",
        })
        if len(rows) >= limit:
            break
    return rows


def build_action_center(
    screener_path: Path,
    income_path: Path,
    study_path: Path | None = None,
    trade_limit: int = 5,
    income_limit: int = 6,
    study_limit: int = 5,
) -> dict[str, Any]:
    scan = _load(screener_path)
    income = _load(income_path)
    study = _load(study_path) if study_path else {}
    rows = _trade_rows(scan, trade_limit) + _study_rows(study, study_limit) + _income_rows(income, income_limit)
    rows.sort(key=lambda r: (r["type"] != "TRADE ENTRY", -int(r.get("priority") or 0)))

    return {
        "built_at": max(
            scan.get("scanned_at") or "",
            income.get("scanned_at") or "",
            study.get("scanned_at") or "",
        ) or None,
        "range_scanned_at": scan.get("scanned_at"),
        "income_scanned_at": income.get("scanned_at"),
        "study_scanned_at": study.get("scanned_at"),
        "summary": {
            "trade_entries": len(scan.get("buys") or []),
            "range_watches": len(scan.get("watches") or []),
            "income_candidates": len(income.get("top_candidates") or []),
            "study_items": len(study.get("all_setups") or []),
        },
        "actions": rows,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build RangeBot action center JSON")
    parser.add_argument("--screener", default="screener_results.json")
    parser.add_argument("--income", default="monthly_income.json")
    parser.add_argument("--study", default=None)
    parser.add_argument("--output", default="action_center.json")
    args = parser.parse_args(argv)

    payload = build_action_center(
        screener_path=Path(args.screener),
        income_path=Path(args.income),
        study_path=Path(args.study) if args.study else None,
    )
    Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Action center saved -> {args.output}")
    print(
        f"Actions: {len(payload['actions'])} | "
        f"trade entries: {payload['summary']['trade_entries']} | "
        f"income: {payload['summary']['income_candidates']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
