"""
cot_feed.py — CFTC Commitment of Traders data for ag futures.

Pulls the Disaggregated Futures-Only report from the CFTC's free public
Socrata API (no key required). We track MANAGED MONEY positioning — the
hedge funds and CTAs whose net position and its week-over-week change
are among the most-watched sentiment gauges in ag markets.

Dataset: https://publicreporting.cftc.gov/resource/72hh-3qpy.json
Published every Friday 2:30 PM CT, with Tuesday's positions.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

import requests

COT_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"

# CFTC contract market codes for our ag universe
CFTC_CODES = {
    "ZC=F": "002602",   # Corn — CBOT
    "ZS=F": "005602",   # Soybeans — CBOT
    "ZW=F": "001602",   # Wheat SRW — CBOT
    "LE=F": "057642",   # Live Cattle — CME
    "GF=F": "061641",   # Feeder Cattle — CME
}


@dataclass
class CotWeek:
    report_date:   str
    mm_long:       float   # managed money long contracts
    mm_short:      float   # managed money short contracts
    open_interest: float

    @property
    def mm_net(self) -> float:
        return self.mm_long - self.mm_short

    @property
    def mm_net_pct_oi(self) -> float:
        """Net position as % of open interest — comparable across contracts."""
        return (self.mm_net / self.open_interest * 100) if self.open_interest else 0.0


def fetch_cot(ticker: str, weeks: int = 60) -> Optional[List[CotWeek]]:
    """
    Fetch recent CoT history for one ag contract, newest LAST.
    Returns None if the ticker has no CFTC code or the fetch fails.
    """
    code = CFTC_CODES.get(ticker)
    if not code:
        return None

    params = {
        "cftc_contract_market_code": code,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": weeks,
        "$select": ("report_date_as_yyyy_mm_dd,"
                    "m_money_positions_long_all,"
                    "m_money_positions_short_all,"
                    "open_interest_all"),
    }
    try:
        r = requests.get(COT_URL, params=params, timeout=20)
        if not r.ok:
            print(f"    CoT API {r.status_code} for {ticker}")
            return None
        rows = r.json()
        if not rows:
            return None
        out = []
        for row in reversed(rows):   # oldest → newest
            out.append(CotWeek(
                report_date   = row.get("report_date_as_yyyy_mm_dd", "")[:10],
                mm_long       = float(row.get("m_money_positions_long_all", 0) or 0),
                mm_short      = float(row.get("m_money_positions_short_all", 0) or 0),
                open_interest = float(row.get("open_interest_all", 0) or 0),
            ))
        return out
    except Exception as e:
        print(f"    CoT fetch failed for {ticker}: {e}")
        return None
