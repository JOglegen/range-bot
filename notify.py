"""
notify.py — Twilio SMS alerts for RangeBot signals.

Sends a single concise SMS when BUY/EXIT signals fire on the S&P 500 scan.
Keeps messages under 320 characters (2 SMS segments) when possible.

Required environment variables (set as GitHub secrets):
  TWILIO_ACCOUNT_SID   — from console.twilio.com
  TWILIO_AUTH_TOKEN    — from console.twilio.com
  TWILIO_FROM          — your Twilio phone number, e.g. +15551234567
  TWILIO_TO            — your cell phone, e.g. +14175551234
"""

from __future__ import annotations
import os
import re
from typing import List, Optional

from screener import Setup


def _normalize_phone(value: str) -> str:
    """Return a Twilio-friendly E.164-ish phone number."""
    raw = re.sub(r"\s+", "", value or "")
    if raw.startswith("+"):
        return raw
    digits = re.sub(r"\D+", "", raw)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return raw


def _fmt_setup(s: Setup, include_levels: bool = True) -> str:
    """Single-line summary of one setup."""
    base = f"{s.symbol} ${s.price:.2f} [{s.score}]"
    if include_levels and s.entry_low and s.target and s.stop:
        return (f"{base}  in:${s.entry_low:.2f}–${s.entry_high:.2f}"
                f"  tgt:${s.target:.2f}  stop:${s.stop:.2f}")
    return base


def build_sms(
    buys:      List[Setup],
    watches:   List[Setup],
    mode:      str,
    scan_time: str,
    total_scanned: int,
) -> str:
    lines = [f"RangeBot {scan_time} CT | {mode.upper()} | {total_scanned} stocks scanned"]

    if buys:
        lines.append(f"\n🟢 BUY ({len(buys)} signal{'s' if len(buys)>1 else ''}):")
        for s in buys[:5]:
            lines.append(f"  {_fmt_setup(s)}")
    else:
        lines.append("\nNo BUY signals today.")

    if watches:
        lines.append(f"\n⚠️  WATCH/EXIT ({len(watches)}):")
        for s in watches[:3]:
            lines.append(f"  {s.symbol} ${s.price:.2f} — {s.note[:40]}")

    lines.append("\ngithub.com/JOglegen/range-bot")
    return "\n".join(lines)


def send_sms(body: str,
             account_sid: Optional[str] = None,
             auth_token:  Optional[str] = None,
             from_:       Optional[str] = None,
             to:          Optional[str] = None) -> bool:
    """
    Send an SMS via Twilio REST API (no SDK needed — pure requests).
    Returns True on success, False on failure.
    """
    import requests as req

    sid   = account_sid or os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = auth_token  or os.environ.get("TWILIO_AUTH_TOKEN", "")
    frm   = _normalize_phone(from_ or os.environ.get("TWILIO_FROM", ""))
    to_   = _normalize_phone(to or os.environ.get("TWILIO_TO", ""))

    missing = [k for k, v in [("SID", sid), ("TOKEN", token),
                                ("FROM", frm), ("TO", to_)] if not v]
    if missing:
        print(f"[notify] Missing Twilio env vars: {missing} — SMS skipped")
        return False

    url  = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = {"From": frm, "To": to_, "Body": body}

    r = req.post(url, data=data, auth=(sid, token), timeout=15)
    if r.ok:
        msg_sid = r.json().get("sid", "?")
        print(f"[notify] SMS sent ✓  sid={msg_sid}  chars={len(body)}")
        return True
    else:
        print(f"[notify] SMS failed {r.status_code}: {r.text[:200]}")
        return False


def notify_signals(
    buys:      List[Setup],
    watches:   List[Setup],
    mode:      str,
    scan_time: str,
    total_scanned: int,
    dry_run:   bool = False,
) -> None:
    """Compose and send the signal SMS. Pass dry_run=True to print without sending."""
    body = build_sms(buys, watches, mode, scan_time, total_scanned)
    print("\n" + "─" * 50)
    print("SMS PREVIEW:")
    print(body)
    print(f"─" * 50)
    print(f"Length: {len(body)} chars (~{len(body)//160 + 1} segment(s))\n")

    if dry_run:
        print("[notify] Dry run — SMS not sent")
        return

    send_sms(body)
