"""Escalation triggers as machine-readable constants.

The build spec's section 11.2 lists when to escalate. Each trigger is a
constant rather than a prose string so the `reason` column in `escalations` is
analysable later -- "why do we escalate?" should be a GROUP BY, not a text
search.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EscalationReason(str, Enum):
    NO_AUTHORITATIVE_SOURCE = "no_authoritative_source"
    VERDICT_UNDECIDABLE = "verdict_undecidable"
    EQUAL_AUTHORITY_CONFLICT = "equal_authority_conflict"
    EXCEPTION_TO_WRITTEN_RULE = "exception_to_written_rule"
    ACTION_OUTSIDE_CAPABILITY = "action_outside_capability"
    HUMAN_REQUESTED = "human_requested"
    STEP_BUDGET_EXHAUSTED = "step_budget_exhausted"
    DERIVED_CLASSIFICATION_DISPUTED = "derived_classification_disputed"
    SLA_BREACHED = "sla_breached"


_DESCRIPTIONS = {
    EscalationReason.NO_AUTHORITATIVE_SOURCE:
        "No supporting source above tier 3 was found.",
    EscalationReason.VERDICT_UNDECIDABLE:
        "The rules could not reach a confident verdict on the available facts.",
    EscalationReason.EQUAL_AUTHORITY_CONFLICT:
        "Two sources of equal authority disagree.",
    EscalationReason.EXCEPTION_TO_WRITTEN_RULE:
        "The request asks for an exception to a written rule.",
    EscalationReason.ACTION_OUTSIDE_CAPABILITY:
        "The request needs an action this system cannot perform.",
    EscalationReason.HUMAN_REQUESTED:
        "The caller explicitly asked for a human.",
    EscalationReason.STEP_BUDGET_EXHAUSTED:
        "The reasoning chain was cut short by the step budget.",
    EscalationReason.DERIVED_CLASSIFICATION_DISPUTED:
        "The answer rests on a derived severity that the caller may dispute.",
    EscalationReason.SLA_BREACHED:
        "A first-response target has already been breached.",
}


@dataclass
class EscalationDraft:
    account_id: str
    created_by: str
    severity: str
    summary: str
    reason: EscalationReason
    reason_detail: str
    order_id: str | None = None
    ticket_id: str | None = None
    linked_sources: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "created_by": self.created_by,
            "severity": self.severity,
            "summary": self.summary,
            "reason": self.reason.value,
            "reason_detail": self.reason_detail,
            "order_id": self.order_id,
            "ticket_id": self.ticket_id,
            "linked_sources": self.linked_sources or [],
        }


def describe(reason: EscalationReason) -> str:
    return _DESCRIPTIONS[reason]


def triggers_from_verdict(verdict: dict[str, Any]) -> list[EscalationReason]:
    """Which escalation triggers a policy verdict fires."""
    reasons: list[EscalationReason] = []
    if verdict.get("outcome") == "undecidable":
        reasons.append(EscalationReason.VERDICT_UNDECIDABLE)
    if verdict.get("outcome") == "breached":
        reasons.append(EscalationReason.SLA_BREACHED)
    if verdict.get("severity_derived") is not None:
        reasons.append(EscalationReason.DERIVED_CLASSIFICATION_DISPUTED)
    return reasons


def triggers_from_conflicts(conflicts: list[dict[str, Any]]) -> list[EscalationReason]:
    if any(not c.get("resolved", True) for c in conflicts):
        return [EscalationReason.EQUAL_AUTHORITY_CONFLICT]
    return []


def triggers_from_sources(top_tier: int | None) -> list[EscalationReason]:
    if top_tier is None or top_tier > 3:
        return [EscalationReason.NO_AUTHORITATIVE_SOURCE]
    return []
