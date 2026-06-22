"""
Offline self-test. No keys, no network. Proves data -> strategy -> risk ->
order wiring end to end against the synthetic series in brokers/mock.py.

Run:  python selftest.py
"""

from __future__ import annotations
import logging

from config import Settings
from risk import RiskManager
from strategy import compute_metrics, signal, score_for
from brokers.mock import MockBroker
from brokers.base import OrderRequest


def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    return cond


def main() -> int:
    print("Strategy signals on synthetic data")
    broker = MockBroker(equity=1000.0)
    ok = True
    for sym, mode, expect in [("AAPL", "range", "BUY"),
                              ("NVDA", "breakout", "BUY"),
                              ("AMD", "range", "EXIT"),
                              ("MSFT", "range", "WAIT")]:
        bars = broker.get_daily_bars(sym)
        m = compute_metrics(bars)
        sig = signal(m, mode)
        print(f"   {sym:5} {mode:9} -> {sig.tag:9} "
              f"(pos {m.pos*100:3.0f}%, score {score_for(m, mode)})")
        ok &= check(f"{sym} {mode} == {expect}", sig.tag == expect)

    print("\nRisk sizing (equity $1000, 1% risk, entry 100 / stop 96)")
    risk = RiskManager(Settings())
    acct = broker.get_account()
    d = risk.size(acct, entry=100.0, stop=96.0)
    # risk budget = $10, per-share risk = $4 -> 2 shares; value cap 25% = $250 -> 2 sh
    ok &= check("sizes to 2 shares", d.qty == 2)
    ok &= check("rejects stop above entry", risk.size(acct, 100.0, 105.0).qty == 0)

    print("\nEnd-to-end: a BUY produces a bracketed order through the broker")
    bars = broker.get_daily_bars("AAPL")
    m = compute_metrics(bars)
    sig = signal(m, "range")
    d = risk.size(acct, m.price, sig.stop)
    broker.submit_order(OrderRequest(symbol="AAPL", qty=d.qty, side="buy",
                                     take_profit=sig.target, stop_loss=sig.stop))
    o = broker.submitted[-1]
    ok &= check("order captured with qty > 0", o.qty > 0)
    ok &= check("bracket stop attached", o.stop_loss is not None)
    ok &= check("bracket target attached", o.take_profit is not None)
    ok &= check("stop below target", o.stop_loss < o.take_profit)

    print("\n" + ("ALL GOOD ✓" if ok else "SOMETHING FAILED ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    raise SystemExit(main())
