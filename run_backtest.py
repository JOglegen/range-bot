"""
run_backtest.py  —  entry point for the Range Bot backtester.

Usage:
  # Full analysis on real data (needs: pip install yfinance + internet)
  python run_backtest.py

  # Offline / sandbox — synthetic data, same engine
  python run_backtest.py --offline

  # Test a specific mode only
  python run_backtest.py --mode breakout --offline

  # Custom symbols, longer history
  python run_backtest.py --symbols NVDA,AMD,AAPL,MSFT,QQQ,SPY --start 2018-01-01

Produces: backtest_report.html  (open in any browser, all charts embedded)
"""

from __future__ import annotations
import argparse
import os
import sys
import warnings
warnings.filterwarnings("ignore")
os.environ.setdefault("MPLBACKEND", "Agg")


def _print_result(label, res, mc=None):
    pf = f"{res.profit_factor:.2f}" if res.profit_factor < 99 else "∞"
    print(f"\n  {label}")
    print(f"  {'─'*44}")
    print(f"  Trades        : {len(res.trades)}")
    print(f"  Win rate      : {res.win_rate:.1f}%")
    print(f"  Avg win/loss  : {res.avg_win_pct:+.2f}% / {res.avg_loss_pct:+.2f}%")
    print(f"  Profit factor : {pf}")
    print(f"  CAGR          : {res.cagr:+.1f}%")
    print(f"  Sharpe        : {res.sharpe:+.2f}")
    print(f"  Sortino       : {res.sortino:+.2f}")
    print(f"  Max drawdown  : {res.max_drawdown_pct:.1f}%")
    print(f"  Final equity  : ${res.final_equity:,.2f}  (started ${res.start_equity:,.0f})")
    print(f"  Exit breakdown: {res.exit_breakdown()}")
    if mc:
        print(f"  MC win % (2000 sims): {mc['win_pct']:.0f}%  "
              f"p5=${mc['final_p5']:,.0f}  median=${mc['final_mean']:,.0f}  "
              f"p95=${mc['final_p95']:,.0f}")


def _assess(label, res, mc=None, wf=None):
    issues, praises = [], []
    if len(res.trades) < 20:
        issues.append(f"Only {len(res.trades)} trades — too few for statistical confidence.")
    else:
        praises.append(f"{len(res.trades)} trades — statistically meaningful sample.")
    pf = res.profit_factor
    if pf < 1.0:
        issues.append(f"Profit factor {pf:.2f} — strategy lost gross money.")
    elif pf < 1.3:
        issues.append(f"Profit factor {pf:.2f} — marginal edge (target ≥ 1.3).")
    else:
        praises.append(f"Profit factor {pf:.2f} — solid gross edge.")
    if res.sharpe < 0:
        issues.append(f"Sharpe {res.sharpe:.2f} — negative risk-adjusted return.")
    elif res.sharpe < 0.5:
        issues.append(f"Sharpe {res.sharpe:.2f} — weak (a boring index fund does better).")
    elif res.sharpe < 1.0:
        praises.append(f"Sharpe {res.sharpe:.2f} — respectable.")
    else:
        praises.append(f"Sharpe {res.sharpe:.2f} — strong risk-adjusted return.")
    if res.max_drawdown_pct > 25:
        issues.append(f"Max DD {res.max_drawdown_pct:.1f}% — severe (hard to stomach).")
    elif res.max_drawdown_pct > 15:
        issues.append(f"Max DD {res.max_drawdown_pct:.1f}% — elevated.")
    else:
        praises.append(f"Max DD {res.max_drawdown_pct:.1f}% — controlled drawdown.")
    if mc:
        if mc["win_pct"] < 55:
            issues.append(f"Only {mc['win_pct']:.0f}% of MC sims profitable — likely luck, not edge.")
        elif mc["win_pct"] > 85:
            praises.append(f"{mc['win_pct']:.0f}% of MC sims profitable — structural edge confirmed.")
        else:
            praises.append(f"{mc['win_pct']:.0f}% of MC sims profitable — edge looks real.")
    if wf:
        oos = wf["out_of_sample"]
        if oos.cagr < 0:
            issues.append(f"Out-of-sample CAGR {oos.cagr:.1f}% — edge evaporated on unseen data.")
        elif oos.sharpe < 0.3:
            issues.append(f"Out-of-sample Sharpe {oos.sharpe:.2f} — edge weakened out-of-sample.")
        else:
            praises.append(f"Out-of-sample Sharpe {oos.sharpe:.2f} — survived the honest test.")
    return praises, issues


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Range Bot backtester")
    p.add_argument("--symbols",   default="AAPL,MSFT,NVDA,AMD,JPM,XOM,KO,WMT")
    p.add_argument("--mode",      default="both", choices=["range","breakout","both"],
                   help="'both' (default) tests both and recommends the better one")
    p.add_argument("--start",     default="2019-01-01")
    p.add_argument("--split",     default="2023-01-01",
                   help="walk-forward train/test split date")
    p.add_argument("--lookback",  type=int, default=20)
    p.add_argument("--min-score", type=int, default=60, dest="min_score")
    p.add_argument("--equity",    type=float, default=10_000.0,
                   help="starting equity for simulation (use 1000 for a $1k account)")
    p.add_argument("--offline",   action="store_true",
                   help="synthetic data — no internet required")
    p.add_argument("--no-walkforward", action="store_true")
    p.add_argument("--no-montecarlo",  action="store_true")
    p.add_argument("--no-sensitivity", action="store_true")
    p.add_argument("--mc-sims",   type=int, default=2000)
    p.add_argument("--output",    default="backtest_report.html")
    args = p.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    print(f"\n{'═'*60}")
    print(f"  Range Bot Backtester")
    print(f"{'═'*60}")
    print(f"  Symbols : {', '.join(symbols)}")
    print(f"  Mode    : {args.mode}  |  Period: {args.start} → today")
    print(f"  Equity  : ${args.equity:,.0f}  |  "
          f"Data: {'synthetic (--offline)' if args.offline else 'Yahoo Finance'}")
    if args.offline:
        print(f"\n  ⚠  SYNTHETIC DATA — results are for logic verification only.")
        print(f"     Run without --offline on your own machine for real results.")
    print(f"{'═'*60}\n")

    from backtest import (run_portfolio, walk_forward, monte_carlo,
                          param_sensitivity, Backtester)
    from data import load_data
    from report import generate_report

    # ── load data once ────────────────────────────────────────────────────────
    print("Loading data...")
    raw = load_data(symbols, start=args.start, offline=args.offline)
    if not raw:
        print("ERROR: no data. Try --offline or check tickers.")
        return 1
    print(f"  Loaded: {', '.join(raw.keys())}\n")

    modes = ["range","breakout"] if args.mode == "both" else [args.mode]
    results = {}

    for mode in modes:
        print(f"Running {mode} mode backtest...")
        res = run_portfolio(raw, mode=mode, lookback=args.lookback,
                            min_score=args.min_score, start_equity=args.equity)
        results[mode] = {"result": res}
        _print_result(mode.upper(), res)

    # ── walk-forward (best/chosen mode only) ─────────────────────────────────
    wf_mode = max(modes, key=lambda m: results[m]["result"].sharpe)
    wf_res = None
    if not args.no_walkforward:
        print(f"\nWalk-forward validation ({wf_mode} mode, split {args.split})...")
        wf_res = walk_forward(symbols, wf_mode, args.split, args.offline,
                              args.start, start_equity=args.equity)
        results[wf_mode]["wf"] = wf_res

    # ── Monte Carlo ───────────────────────────────────────────────────────────
    for mode in modes:
        if not args.no_montecarlo and results[mode]["result"].trades:
            print(f"\nMonte Carlo — {mode} mode ({args.mc_sims:,} sims)...")
            mc = monte_carlo(results[mode]["result"].trades, args.equity,
                             n_sims=args.mc_sims)
            results[mode]["mc"] = mc
            print(f"  Win%: {mc['win_pct']:.0f}%  "
                  f"p5=${mc['final_p5']:,.0f}  median=${mc['final_mean']:,.0f}  "
                  f"p95=${mc['final_p95']:,.0f}")

    # ── sensitivity (best mode) ───────────────────────────────────────────────
    sensitivity = None
    if not args.no_sensitivity:
        print(f"\nParameter sensitivity ({wf_mode} mode)...")
        sensitivity = param_sensitivity(raw, wf_mode, symbols, args.equity)
        print("  Done.")

    # ── honest assessment ─────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("HONEST ASSESSMENT")
    print(f"{'─'*60}")
    for mode in modes:
        r = results[mode]
        praises, issues = _assess(mode, r["result"], r.get("mc"), r.get("wf"))
        print(f"\n  {mode.upper()} mode:")
        for pr in praises:
            print(f"    ✓ {pr}")
        for iss in issues:
            print(f"    ✗ {iss}")

    # Recommendation
    print(f"\n{'─'*60}")
    if args.mode == "both":
        rs = {m: results[m]["result"].sharpe for m in modes}
        best = max(rs, key=rs.get)
        worst = min(rs, key=rs.get)
        print(f"RECOMMENDATION: {best.upper()} mode is stronger "
              f"(Sharpe {rs[best]:.2f} vs {rs[worst]:.2f}).")
        if rs[best] > 0.8:
            print(f"  → Run the bot in {best.upper()} mode. Paper-trade 4+ weeks first.")
        elif rs[best] > 0:
            print(f"  → Marginal edge. Paper-trade and monitor. Don't scale up yet.")
        else:
            print(f"  → Neither mode shows edge on this data.")
            print(f"     If using --offline: run with real data (yfinance) for honest results.")
    else:
        best_r = results[args.mode]["result"]
        if best_r.sharpe > 0.8 and best_r.profit_factor > 1.3:
            print(f"  → Looks solid. Paper-trade 4+ weeks before going live.")
        elif best_r.sharpe <= 0:
            print(f"  → Do NOT trade live. Adjust parameters or try breakout mode.")
        else:
            print(f"  → Marginal. Paper-trade first. Consider --mode breakout.")

    if args.offline:
        print(f"\n  NOTE: These results use SYNTHETIC data. On real market data")
        print(f"  (run without --offline on your machine), results may differ")
        print(f"  substantially — especially for the range strategy.")

    # ── generate HTML report (for best mode) ─────────────────────────────────
    print(f"\nGenerating HTML report for {wf_mode} mode...")
    b = results[wf_mode]
    html = generate_report(
        res=b["result"],
        wf=b.get("wf"),
        mc=b.get("mc"),
        sensitivity=sensitivity,
        title=f"Range Bot — {wf_mode.title()} mode backtest",
        note="synthetic" if args.offline else "",
    )
    with open(args.output, "w") as f:
        f.write(html)
    print(f"  → {args.output}")
    print(f"     Open in any browser. All charts embedded, no internet needed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
