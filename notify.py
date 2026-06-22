"""
notify.py - Twilio SMS alerts for RangeBot signals.

Set these as GitHub Actions repository secrets:
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_FROM
  TWILIO_TO            one or more recipient numbers, comma/newline separated
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


def _recipient_numbers(value: str) -> list[str]:
    """Split and normalize one or more Twilio recipient numbers."""
    parts = [p for p in re.split(r"[,;\n\r\t ]+", value or "") if p.strip()]
    numbers = []
    for part in parts:
        phone = _normalize_phone(part)
        if phone and phone not in numbers:
            numbers.append(phone)
    return numbers


def _fmt_setup(s: Setup, include_levels: bool = True) -> str:
    """Single-line summary of one setup."""
    base = f"{s.symbol} ${s.price:.2f} [{s.score}]"
    if include_levels and s.entry_low and s.target and s.stop:
        return (f"{base}  in:${s.entry_low:.2f}-{s.entry_high:.2f}"
                f"  tgt:${s.target:.2f}  stop:${s.stop:.2f}")
    return base


def build_sms(
    buys: List[Setup],
    watches: List[Setup],
    mode: str,
    scan_time: str,
    total_scanned: int,
) -> str:
    lines = [f"RangeBot {scan_time} CT | {mode.upper()} | {total_scanned} stocks scanned"]

    if buys:
        lines.append(f"\nBUY ({len(buys)} signal{'s' if len(buys) > 1 else ''}):")
        for s in buys[:5]:
            lines.append(f"  {_fmt_setup(s)}")
    else:
        lines.append("\nNo BUY signals today.")

    if watches:
        lines.append(f"\nWATCH/EXIT ({len(watches)}):")
        for s in watches[:3]:
            lines.append(f"  {s.symbol} ${s.price:.2f} - {s.note[:40]}")

    lines.append("\ngithub.com/JOglegen/range-bot")
    return "\n".join(lines)


def send_sms(body: str,
             account_sid: Optional[str] = None,
             auth_token: Optional[str] = None,
             from_: Optional[str] = None,
             to: Optional[str] = None) -> bool:
    """
    Send an SMS via Twilio REST API. Supports multiple recipients in TWILIO_TO.
    Returns True only when every recipient is sent successfully.
    """
    import requests as req

    sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN", "")
    frm = _normalize_phone(from_ or os.environ.get("TWILIO_FROM", ""))
    recipients = _recipient_numbers(to or os.environ.get("TWILIO_TO", ""))

    missing = [k for k, v in [("SID", sid), ("TOKEN", token),
                              ("FROM", frm), ("TO", recipients)] if not v]
    if missing:
        print(f"[notify] Missing Twilio env vars: {missing} - SMS skipped")
        return False

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    ok_count = 0
    for to_ in recipients:
        data = {"From": frm, "To": to_, "Body": body}
        r = req.post(url, data=data, auth=(sid, token), timeout=15)
        if r.ok:
            ok_count += 1
            msg_sid = r.json().get("sid", "?")
            print(f"[notify] SMS sent to {to_}  sid={msg_sid}  chars={len(body)}")
        else:
            print(f"[notify] SMS failed for {to_} {r.status_code}: {r.text[:200]}")
    return ok_count == len(recipients)


def notify_signals(
    buys: List[Setup],
    watches: List[Setup],
    mode: str,
    scan_time: str,
    total_scanned: int,
    dry_run: bool = False,
) -> None:
    """Compose and send the signal SMS. Pass dry_run=True to print without sending."""
    body = build_sms(buys, watches, mode, scan_time, total_scanned)
    print("\n" + "-" * 50)
    print("SMS PREVIEW:")
    print(body)
    print("-" * 50)
    print(f"Length: {len(body)} chars (~{len(body) // 160 + 1} segment(s))\n")

    if dry_run:
        print("[notify] Dry run - SMS not sent")
        return

    send_sms(body)
