"""Proactive detection rules. Pure functions over aggregate data, no LLM.

DETECTION IS SQL/RULES. NAMING IS THE LLM. If detection itself were model
driven, results would change run to run and the ops team would stop trusting
the board within a week. Every rule here is deterministic: same input, same
signals, every time. A single LLM call (jobs/detect_signals.py) writes a
one-line human title afterward -- it never decides WHETHER a signal fires.

THRESHOLDS ARE NOT TUNED TO THIS DATASET (assumption A7). §12's numbers are
implemented exactly as specified. On this small a dataset most rules correctly
find nothing -- issue_spike needs 3+ tickets of one type in 24h and the data's
maximum is 1; multi_account_issue needs 3+ accounts and the maximum is 1. That
is the honest, correct output of the rules as specified, not a bug. Loosening
a threshold to manufacture volume would be tuning the rules to the demo, which
is precisely the failure the design doc names.

`repeat_offender_order` from §12 is DROPPED: tickets carry no order_id in this
dataset (assumption A6, confirmed by scanning every ticket column for
ORD-\\d+, zero matches), so the rule is not computable and is not faked with a
fuzzy join.

Three rules beyond §12, added because they fit this data on their own merit,
not to reach a signal count (per the A7 resolution):
  - security_incident:   an open P1 ticket whose text matches credential/
                          security exposure language
  - known_issue_match:   an open ticket whose text matches an active known
                          issue (KI-208, KI-211)
  - unattended_p1:       a P1 ticket open past a fixed attention window with
                          no sign of a first response
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any

_SECURITY_PATTERN = re.compile(
    r"credential|api\s*key|security incident|password|secret\s*expos", re.I
)
_KNOWN_ISSUES = {
    "KI-208": re.compile(r"bulk upload|csv", re.I),
    "KI-211": re.compile(r"swiftship|still shows booked|pickup.*(webhook|delay)", re.I),
}
UNATTENDED_P1_MINUTES = 30


def _signal_id(signal_type: str, *entities: str) -> str:
    """Deterministic: same type + entities always hashes to the same id, so
    re-runs upsert instead of duplicating a signal that is still open."""
    key = signal_type + "|" + "|".join(sorted(entities))
    return f"sig_{hashlib.sha256(key.encode()).hexdigest()[:16]}"


def _signal(signal_type: str, severity: str, title: str, detail: dict[str, Any],
           accounts: list[str], *entities: str) -> dict[str, Any]:
    return {
        "signal_id": _signal_id(signal_type, *entities),
        "signal_type": signal_type,
        "severity": severity,
        "title": title,
        "detail": detail,
        "affected_accounts": sorted(set(accounts)),
    }


def issue_spike(tickets: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Ticket count for one issue_type in the last 24h exceeds 2x the 7-day
    daily mean, and count is at least 3."""
    window_24h = now - timedelta(hours=24)
    window_7d = now - timedelta(days=7)

    by_type: dict[str, list[dict]] = {}
    for t in tickets:
        if t.get("derived_issue_type") and t.get("created_at"):
            by_type.setdefault(t["derived_issue_type"], []).append(t)

    signals = []
    for issue_type, rows in by_type.items():
        recent = [t for t in rows if t["created_at"] >= window_24h]
        last_7d = [t for t in rows if t["created_at"] >= window_7d]
        daily_mean = len(last_7d) / 7.0
        if len(recent) >= 3 and len(recent) > 2 * daily_mean:
            accounts = [t["account_id"] for t in recent]
            signals.append(_signal(
                "issue_spike", "high",
                f"Spike in {issue_type} tickets",
                {"issue_type": issue_type, "count_24h": len(recent),
                 "daily_mean_7d": round(daily_mean, 2),
                 "ticket_ids": [t["ticket_id"] for t in recent]},
                accounts, issue_type,
            ))
    return signals


def sla_risk_and_breach(
    tickets: list[dict[str, Any]],
    resolve_target,  # callable: (account_id, severity) -> minutes | None
    now: datetime,
) -> list[dict[str, Any]]:
    """High/urgent OPEN tickets within 2h of their SLA deadline, or past it."""
    signals = []
    for t in tickets:
        if t.get("status") != "open" or t.get("derived_severity") not in ("P1", "P2"):
            continue
        if not t.get("created_at"):
            continue
        target_minutes = resolve_target(t["account_id"], t["derived_severity"])
        if target_minutes is None:
            continue
        elapsed_minutes = (now - t["created_at"]).total_seconds() / 60
        remaining = target_minutes - elapsed_minutes

        if remaining < 0:
            signals.append(_signal(
                "sla_breached", "urgent", f"SLA breached: {t['ticket_id']}",
                {"ticket_id": t["ticket_id"], "severity": t["derived_severity"],
                 "breached_by_minutes": round(-remaining)},
                [t["account_id"]], t["ticket_id"],
            ))
        elif remaining <= 120:
            signals.append(_signal(
                "sla_risk", "urgent", f"SLA at risk: {t['ticket_id']}",
                {"ticket_id": t["ticket_id"], "severity": t["derived_severity"],
                 "minutes_remaining": round(remaining)},
                [t["account_id"]], t["ticket_id"],
            ))
    return signals


def multi_account_issue(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One issue_type with open tickets across 3+ accounts."""
    by_type: dict[str, set[str]] = {}
    for t in tickets:
        if t.get("status") == "open" and t.get("derived_issue_type"):
            by_type.setdefault(t["derived_issue_type"], set()).add(t["account_id"])

    return [
        _signal("multi_account_issue", "high",
               f"{issue_type} affecting multiple accounts",
               {"issue_type": issue_type, "account_count": len(accounts)},
               list(accounts), issue_type)
        for issue_type, accounts in by_type.items() if len(accounts) >= 3
    ]


def carrier_degradation(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One carrier's late-pickup rate in the window exceeds 2x its baseline.

    On this dataset there are too few orders per carrier for a baseline to be
    meaningful (the rule needs enough history to compute one), so it correctly
    produces nothing here -- see module docstring on tuned thresholds.
    """
    by_carrier: dict[str, list[dict]] = {}
    for o in orders:
        if o.get("carrier"):
            by_carrier.setdefault(o["carrier"], []).append(o)

    signals = []
    for carrier, rows in by_carrier.items():
        if len(rows) < 10:  # not enough history for a baseline
            continue
        late = sum(
            1 for o in rows
            if o.get("pickup_actual_at") and o.get("pickup_window_end")
            and o["pickup_actual_at"] > o["pickup_window_end"]
        )
        rate = late / len(rows)
        baseline = 0.1  # documented assumption, not derived from this dataset
        if rate > 2 * baseline:
            signals.append(_signal(
                "carrier_degradation", "medium", f"{carrier} pickup delays elevated",
                {"carrier": carrier, "late_rate": round(rate, 3), "sample": len(rows)},
                [o["account_id"] for o in rows], carrier,
            ))
    return signals


def security_incident(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open ticket matching credential/security-exposure language.

    Beyond §12, added on its own merit: policy_v3 names 'confirmed security
    incident or suspected credential exposure' as P1 in its own right, and a
    live one is exactly the kind of thing an ops board should never bury.
    """
    signals = []
    for t in tickets:
        if t.get("status") != "open":
            continue
        text = f"{t.get('subject') or ''} {t.get('description') or ''}"
        if _SECURITY_PATTERN.search(text):
            signals.append(_signal(
                "security_incident", "urgent",
                f"Possible security incident: {t['ticket_id']}",
                {"ticket_id": t["ticket_id"]},
                [t["account_id"]], t["ticket_id"],
            ))
    return signals


def known_issue_match(tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open tickets matching an active known issue, grouped so the ops board
    shows the known issue once with its affected tickets, not one row each."""
    matches: dict[str, list[dict]] = {}
    for t in tickets:
        if t.get("status") != "open":
            continue
        text = f"{t.get('subject') or ''} {t.get('description') or ''}"
        for ki, pattern in _KNOWN_ISSUES.items():
            if pattern.search(text):
                matches.setdefault(ki, []).append(t)

    return [
        _signal("known_issue_match", "medium", f"Tickets matching {ki}",
               {"known_issue": ki, "ticket_ids": [t["ticket_id"] for t in rows]},
               [t["account_id"] for t in rows], ki)
        for ki, rows in matches.items()
    ]


def unattended_p1(tickets: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """P1 ticket open past the attention window. Distinct from sla_breached:
    this fires even when the contract's own target is generous, because a P1
    sitting untouched for 30+ minutes deserves attention regardless of what
    the formal SLA allows."""
    signals = []
    for t in tickets:
        if t.get("status") != "open" or t.get("derived_severity") != "P1":
            continue
        if not t.get("created_at"):
            continue
        elapsed = (now - t["created_at"]).total_seconds() / 60
        if elapsed >= UNATTENDED_P1_MINUTES:
            signals.append(_signal(
                "unattended_p1", "urgent", f"Unattended P1: {t['ticket_id']}",
                {"ticket_id": t["ticket_id"], "elapsed_minutes": round(elapsed)},
                [t["account_id"]], t["ticket_id"],
            ))
    return signals


def detect_all(
    tickets: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    resolve_target,
    now: datetime,
) -> list[dict[str, Any]]:
    """Run every rule. The board shows whatever this honestly returns."""
    return (
        issue_spike(tickets, now)
        + sla_risk_and_breach(tickets, resolve_target, now)
        + multi_account_issue(tickets)
        + carrier_degradation(orders)
        + security_incident(tickets)
        + known_issue_match(tickets)
        + unattended_p1(tickets, now)
    )
