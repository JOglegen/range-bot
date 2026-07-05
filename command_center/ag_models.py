"""
ag_models.py — CoT-based voting models for ag futures.

Two additional models that only ag contracts get:

1. cot_extreme — WHERE is managed money positioned vs its own 1-year range?
   Crowded extremes are contrarian: when funds are max-long there's nobody
   left to buy (fade it); when max-short, the fuel for a short-covering
   rally is loaded (buy signal).

2. cot_momentum — WHICH WAY is positioning moving over the last 4 weeks?
   Funds building longs = trend confirmation (buy); funds liquidating =
   headwind (sell).

Both return the same Vote type as the technical models, so they slot
straight into the consensus ballot.
"""

from __future__ import annotations
from typing import List, Optional

from command_center.models import Vote
from command_center.cot_feed import CotWeek


def model_cot_extreme(history: List[CotWeek]) -> Vote:
    """Managed money net position vs its own 1-year range (percentile)."""
    if not history or len(history) < 12:
        return Vote("cot_extreme", 0, 0, "insufficient CoT history")

    nets = [w.mm_net_pct_oi for w in history]
    cur = nets[-1]
    lo, hi = min(nets), max(nets)
    span = hi - lo or 1e-9
    pct = (cur - lo) / span   # 0 = most short of the year, 1 = most long

    # Contrarian at the extremes
    if pct <= 0.15:
        return Vote("cot_extreme", 1, round(pct, 2),
                    f"funds near max-short ({pct:.0%} of 1y range) — squeeze fuel")
    if pct >= 0.85:
        return Vote("cot_extreme", -1, round(pct, 2),
                    f"funds near max-long ({pct:.0%} of 1y range) — crowded")
    return Vote("cot_extreme", 0, round(pct, 2),
                f"positioning mid-range ({pct:.0%} of 1y range)")


def model_cot_momentum(history: List[CotWeek]) -> Vote:
    """4-week change in managed money net position (as % of OI)."""
    if not history or len(history) < 5:
        return Vote("cot_momentum", 0, 0, "insufficient CoT history")

    cur   = history[-1].mm_net_pct_oi
    prior = history[-5].mm_net_pct_oi
    delta = cur - prior   # percentage points of OI

    if delta > 3:
        return Vote("cot_momentum", 1, round(delta, 1),
                    f"funds added {delta:+.1f}pp of OI in 4wk — accumulating")
    if delta < -3:
        return Vote("cot_momentum", -1, round(delta, 1),
                    f"funds cut {delta:+.1f}pp of OI in 4wk — liquidating")
    return Vote("cot_momentum", 0, round(delta, 1),
                f"positioning steady ({delta:+.1f}pp over 4wk)")


def cot_votes(history: Optional[List[CotWeek]]) -> List[Vote]:
    """Run both CoT models. Returns [] if no CoT data (non-ag assets)."""
    if not history:
        return []
    return [model_cot_extreme(history), model_cot_momentum(history)]
