"""
Runner: one pass over the watchlist. Designed to be run once per day on a
schedule (cron / Task Scheduler / a GitHub Action), a few minutes before the
close, since this is a daily-bar strategy.

Flow per run:
  account + positions  ->  risk gate  ->  for each symbol:
      bars -> metrics -> signal -> (entry? size & bracket order) / (exit? close)

Safety:
  * Defaults to the mock broker if you run it with no arguments.
  * --dry-run computes and prints intended orders but submits nothing.
  * Going live (real money) requires broker="schwab" or "alpaca_live" AND the
    explicit --i-understand-live flag.
"""

from __future__ import annotations
import argparse
import logging
import sys

from config import load_settings, Settings
from strategy import Bar, compute_metrics, signal, score_for
from risk import RiskManager
from brokers.base import Broker, OrderRequest

log = logging.getLogger("range_bot")


def build_broker(s: Settings) -> Broker:
    if s.broker == "mock":
        from brokers.mock import MockBroker
        return MockBroker(equity=1000.0)
    if s.broker in ("alpaca_paper", "alpaca_live"):
        from brokers.alpaca import AlpacaBroker
        return AlpacaBroker(s.alpaca_key, s.alpaca_secret,
                            paper=(s.broker == "alpaca_paper"), feed=s.data_feed)
    if s.broker == "schwab":
        from brokers.schwab import SchwabBroker
        return SchwabBroker(s.schwab_app_key, s.schwab_app_secret,
                            s.schwab_refresh_token, s.schwab_account_hash)
    raise ValueError(s.broker)


def run_once(s: Settings, dry_run: bool = False) -> None:
    broker = build_broker(s)
    risk = RiskManager(s)

    account = broker.get_account()
    positions = broker.get_positions()
    log.info("Broker=%s  equity=$%.2f  day P&L=%.2f%%  open=%d  mode=%s%s",
             broker.name, account.equity, account.day_pl_pct * 100,
             len(positions), s.mode, "  [DRY RUN]" if dry_run else "")

    can_open, why = risk.can_open_new(account, len(positions))
    if not can_open:
        log.warning("New entries blocked: %s", why)

    for sym in s.watchlist:
        try:
            bars = broker.get_daily_bars(sym, limit=s.lookback + 25)
        except Exception as e:
            log.error("%s: data error: %s", sym, e, exc_info=True)
            continue

        m = compute_metrics(bars, lookback=s.lookback)
        if m is None:
            log.info("%s: not enough history", sym)
            continue

        sig = signal(m, s.mode)
        sc = score_for(m, s.mode)
        held = sym in positions
        log.info("%-5s $%-8.2f pos %3.0f%%  %-9s score %3d  vol %.2fx%s",
                 sym, m.price, m.pos * 100, sig.tag, sc, m.vol_ratio,
                 "  [HELD]" if held else "")

        # ---- exits first ----
        # RANGE mode: EXIT blocks new entries but lets bracket positions ride
        #             to their stop/target (the broker holds those orders).
        # BREAKOUT mode: BREAKDOWN = thesis busted, close immediately.
        should_close = (s.mode == "breakout" and sig.is_exit)
        if held and should_close:
            if dry_run:
                log.info("   -> would CLOSE %s (breakdown signal)", sym)
            else:
                broker.close_position(sym)
                log.info("   -> CLOSED %s (breakdown signal)", sym)
            continue

        # ---- entries ----
        if sig.is_entry and not held:
            if not can_open:
                continue
            if sc < s.min_score:
                log.info("   -> skip: score %d < min %d", sc, s.min_score)
                continue
            if sig.stop is None:
                continue
            entry_px = m.price
            decision = risk.size(account, entry_px, sig.stop)
            if decision.qty <= 0:
                log.info("   -> skip: %s", decision.reason)
                continue

            tp = sig.target if s.use_bracket_orders else None
            sl = sig.stop if s.use_bracket_orders else None
            # Pre-flight: stop must be meaningfully below current price.
            # If the stock has dropped since the close signal, the range
            # may have already been violated — skip rather than submit a
            # bracket where the stop is above the fill.
            if sl and sl >= entry_px * 0.995:
                log.info("   -> skip %s: stop $%.2f too close to entry $%.2f "
                         "(stock may have moved since close)", sym, sl, entry_px)
                continue

            order = OrderRequest(
                symbol=sym, qty=decision.qty, side="buy",
                type=s.entry_order_type,
                limit_price=entry_px if s.entry_order_type == "limit" else None,
                take_profit=tp, stop_loss=sl,
            )
            bracket = (f" bracket[tp ${tp:.2f} / sl ${sl:.2f}]"
                       if tp and sl else "")
            if dry_run:
                log.info("   -> would BUY %d %s @ ~$%.2f  (%s)%s",
                         decision.qty, sym, entry_px, decision.reason, bracket)
            else:
                try:
                    broker.submit_order(order)
                    log.info("   -> BUY %d %s @ ~$%.2f  (%s)%s",
                             decision.qty, sym, entry_px, decision.reason, bracket)
                except RuntimeError as e:
                    log.warning("   -> ORDER SKIPPED %s: %s", sym, e)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="20-day range trading bot")
    p.add_argument("--dry-run", action="store_true",
                   help="compute and print intended orders, submit nothing")
    p.add_argument("--broker", help="override config broker "
                   "(mock | alpaca_paper | alpaca_live | schwab)")
    p.add_argument("--mode", help="override config mode (range | breakout)")
    p.add_argument("--i-understand-live", action="store_true",
                   help="required to trade real money (alpaca_live / schwab)")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")

    s = load_settings()
    if args.broker:
        s.broker = args.broker
    if args.mode:
        s.mode = args.mode
    s.validate()

    if s.broker in ("alpaca_live", "schwab") and not args.i_understand_live:
        log.error("Refusing to run a REAL-MONEY broker (%s) without "
                  "--i-understand-live. Prove it on alpaca_paper first.", s.broker)
        return 2

    run_once(s, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
