"""Derive ticket severity and issue type. Deterministic, no LLM.

The workbook has no `severity` and no `issue_type` column, but the SLA rules
and half the detection rules need both (design doc assumptions A4 and A5). So
they are DERIVED here, from the ticket's own subject and description, against
the severity definitions written in Support Policy v3 section 2.

Two consequences, both deliberate:

1. Every surface that shows these values must label them as DERIVED, not as
   source truth, and every SLA answer must state the derivation inline. A
   confident "your SLA is breached" resting on an unstated inference is exactly
   the failure mode this system exists to avoid.
2. When no rule matches with confidence, the result is None -- which flows to
   `undecidable` and then to escalation. Guessing a severity would silently
   change a target from 15 minutes to 8 business hours.

Rules over an LLM classifier because the same ticket must classify the same way
on every run; a board that reshuffles between runs stops being trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Policy v3 section 2: "Complete production outage preventing all shipment
# creation for a customer, confirmed security incident or suspected credential
# exposure, or another event causing immediate material business risk with no
# workaround."
_P1_PATTERNS: list[tuple[str, str]] = [
    (r"\ball\s+shipment\s+creation\b.*\b(fail|down|error)", "all shipment creation failing"),
    (r"\bevery\s+user\b.*\b(fail|error|500)\b", "affects every user"),
    (r"\b(complete|total)\s+(outage|failure)\b", "complete outage"),
    (r"\bapi\s*key\b.*\b(expos|leak|public|screenshot)", "suspected credential exposure"),
    (r"\b(credential|secret|token)\b.*\b(expos|leak|public)", "suspected credential exposure"),
    (r"\bsecurity\s+incident\b", "security incident"),
]

# "Major feature unavailable or materially degraded for a customer, but core
# operations remain possible or a workaround exists."
_P2_PATTERNS: list[tuple[str, str]] = [
    (r"\bbulk\s+upload\b.*\b(fail|error)", "major feature degraded"),
    (r"\b(unavailable|degraded|failing)\b", "feature degraded"),
]

# Evidence that core operations still work -> caps severity at P2.
_WORKAROUND = re.compile(
    r"\b(still works|one-by-one|workaround|unaffected|can still)\b", re.I
)

# "Minor defect, how-to question, configuration request, or issue with limited
# operational impact."
_P3_PATTERNS: list[tuple[str, str]] = [
    (r"\bhow\s+(do|to|can)\b", "how-to question"),
    (r"\b(change|update|replace)\s+the\b.*\b(contact|email|address|setting)", "configuration request"),
    (r"\bstill\s+shows\b", "display/status discrepancy, limited operational impact"),
]

_ISSUE_TYPES: list[tuple[str, str]] = [
    (r"\bapi\s*key|credential|security|expos", "security"),
    (r"\ball\s+shipment\s+creation|every\s+user|outage|http\s*500", "outage"),
    (r"\bbulk\s+upload|csv", "bulk_upload"),
    (r"\bpickup|booked|picked[_ ]?up|webhook", "pickup_status"),
    (r"\bbilling|contact|account\s+setting", "account_admin"),
]


@dataclass(frozen=True)
class Classification:
    severity: str | None
    rationale: str
    issue_type: str | None


def classify_ticket(subject: str | None, description: str | None) -> Classification:
    text = f"{subject or ''} {description or ''}".strip()
    if not text:
        return Classification(None, "no subject or description to classify", None)

    lowered = text.lower()
    issue_type = next(
        (name for pattern, name in _ISSUE_TYPES if re.search(pattern, lowered)), None
    )

    for pattern, reason in _P1_PATTERNS:
        if re.search(pattern, lowered):
            return Classification("P1", f"P1: {reason} (Support Policy v3 s2)", issue_type)

    has_workaround = bool(_WORKAROUND.search(text))
    for pattern, reason in _P2_PATTERNS:
        if re.search(pattern, lowered):
            detail = f"{reason}, workaround available" if has_workaround else reason
            return Classification("P2", f"P2: {detail} (Support Policy v3 s2)", issue_type)

    for pattern, reason in _P3_PATTERNS:
        if re.search(pattern, lowered):
            return Classification("P3", f"P3: {reason} (Support Policy v3 s2)", issue_type)

    # No confident match. None flows to undecidable, then to a human.
    return Classification(
        None,
        "no severity rule matched with confidence; requires human classification",
        issue_type,
    )
