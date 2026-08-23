"""Conflict detection between retrieved sources. Rules first, no LLM.

Mirrors the detection philosophy used for signals: deterministic rules decide
WHETHER there is a conflict, and only prose describing it is ever model-written.
A model-driven conflict detector changes its mind between runs, and a trust
feature that is not reproducible is not a trust feature.

Chunks are reduced to claim tuples (subject key, numeric value, unit). Two
different documents asserting different values for one subject is a conflict.
Tier decides the winner. Equal tier is UNRESOLVED and escalates, per the build
spec's section 6.1.

KNOWN LIMITATION, DELIBERATELY VISIBLE: the subject lexicon below is small, so
conflicts on subjects outside it are not detected. Those subjects are LOGGED
rather than silently dropped, because limited coverage is something to name in
the product note, not to discover in a demo.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# subject_key -> patterns that indicate the chunk is talking about that subject
_SUBJECT_LEXICON: dict[str, list[str]] = {
    "cancellation_fee_window": [
        r"cancellation fee", r"no fee within", r"free cancellation",
        r"cancel .* shipment", r"cancellation-fee",
    ],
    "service_credit_threshold": [
        r"past the end of the scheduled pickup window", r"failed-pickup",
        r"service credit", r"service-credit",
    ],
    "sla_first_response": [
        r"first-response", r"first response", r"response target",
        r"\bP1\b.*\bP2\b", r"response targets",
    ],
    "bulk_upload_limit": [
        r"bulk upload", r"rows per csv", r"row limit",
    ],
}

_NUMBER = re.compile(
    r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>minutes?|hours?|business hours?|business days?|days?|rows?|%|percent)",
    re.I,
)
_CURRENCY = re.compile(r"INR\s*(?P<value>\d[\d,]*(?:\.\d+)?)", re.I)


@dataclass(frozen=True)
class Claim:
    subject: str
    value: float
    unit: str
    doc_id: str
    authority_tier: int
    chunk_id: int
    excerpt: str


@dataclass
class Conflict:
    subject: str
    winning_doc: str
    losing_doc: str
    winning_value: str
    losing_value: str
    reason: str
    resolved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "winning_doc": self.winning_doc,
            "losing_doc": self.losing_doc,
            "winning_value": self.winning_value,
            "losing_value": self.losing_value,
            "reason": self.reason,
            "resolved": self.resolved,
        }


def _subjects_for(text: str) -> list[str]:
    lowered = text.lower()
    return [
        subject
        for subject, patterns in _SUBJECT_LEXICON.items()
        if any(re.search(p, lowered) for p in patterns)
    ]


def _normalise_unit(unit: str) -> str:
    unit = unit.lower().strip().rstrip("s")
    return {"percent": "%", "business hour": "business_hour",
            "business day": "business_day"}.get(unit, unit)


def extract_claims(chunk) -> list[Claim]:
    text = chunk.content
    subjects = _subjects_for(text)

    if not subjects:
        # Named, not dropped: this is the coverage limitation made visible.
        log.info(
            "conflict.subject_out_of_lexicon doc_id=%s chunk_id=%s",
            chunk.doc_id, chunk.chunk_id,
        )
        return []

    claims: list[Claim] = []
    for subject in subjects:
        for match in _NUMBER.finditer(text):
            claims.append(Claim(
                subject=subject,
                value=float(match.group("value").replace(",", "")),
                unit=_normalise_unit(match.group("unit")),
                doc_id=chunk.doc_id,
                authority_tier=chunk.authority_tier,
                chunk_id=chunk.chunk_id,
                excerpt=text[max(0, match.start() - 60):match.end() + 40].strip(),
            ))
        for match in _CURRENCY.finditer(text):
            claims.append(Claim(
                subject=subject,
                value=float(match.group("value").replace(",", "")),
                unit="INR",
                doc_id=chunk.doc_id,
                authority_tier=chunk.authority_tier,
                chunk_id=chunk.chunk_id,
                excerpt=text[max(0, match.start() - 60):match.end() + 40].strip(),
            ))
    return claims


def detect(chunks: list) -> list[Conflict]:
    """Compare claims across documents and report contradictions."""
    claims: list[Claim] = []
    for chunk in chunks:
        claims.extend(extract_claims(chunk))

    # (subject, unit) -> doc_id -> values
    grouped: dict[tuple[str, str], dict[str, list[Claim]]] = {}
    for claim in claims:
        grouped.setdefault((claim.subject, claim.unit), {}).setdefault(
            claim.doc_id, []
        ).append(claim)

    conflicts: list[Conflict] = []
    for (subject, unit), by_doc in grouped.items():
        if len(by_doc) < 2:
            continue

        # One representative value per document: the claim closest to the
        # subject's own wording is not knowable here, so the minimum is used
        # deterministically.
        representatives = {
            doc_id: min(items, key=lambda c: c.value)
            for doc_id, items in by_doc.items()
        }
        values = {c.value for c in representatives.values()}
        if len(values) < 2:
            continue

        ordered = sorted(representatives.values(), key=lambda c: c.authority_tier)
        winner, loser = ordered[0], ordered[-1]

        if winner.authority_tier == loser.authority_tier:
            conflicts.append(Conflict(
                subject=subject,
                winning_doc=winner.doc_id,
                losing_doc=loser.doc_id,
                winning_value=f"{winner.value:g} {unit}",
                losing_value=f"{loser.value:g} {unit}",
                reason=(
                    "two sources of equal authority disagree; this needs a human "
                    "rather than a choice"
                ),
                resolved=False,
            ))
        else:
            conflicts.append(Conflict(
                subject=subject,
                winning_doc=winner.doc_id,
                losing_doc=loser.doc_id,
                winning_value=f"{winner.value:g} {unit}",
                losing_value=f"{loser.value:g} {unit}",
                reason=(
                    f"tier {winner.authority_tier} overrides tier "
                    f"{loser.authority_tier}"
                ),
                resolved=True,
            ))

    return conflicts
