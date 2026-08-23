"""Every formula in the system. Pure functions, no SQL, no LLM.

This is where a reviewer checks the reasoning, so the non-obvious rules are
commented rather than merely implemented.

THREE RULES THAT GOVERN EVERYTHING HERE:

1. Time is measured from `system_meta.snapshot_time`, never `datetime.now()`.
   It is passed in as an argument so there is no way to reach a wall clock.
2. `working` is a human-readable list of the actual steps. It goes into the UI.
   A support agent who can see the arithmetic will trust the system; one who
   cannot, will not.
3. A missing term or an ambiguous fact returns `undecidable` with a reason,
   which flows straight to escalation. Never guess a number to fill a gap.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from app.services.terms import TermSet

Outcome = str


@dataclass
class Verdict:
    rule: str
    outcome: Outcome
    reason_code: str
    working: list[str] = field(default_factory=list)
    amount_inr: float | None = None
    override_applied: bool = False
    governing_source: str | None = None
    sources: list[str] = field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "high"
    # Known-issue ids whose truth could INVERT this verdict. Structural, not
    # prose: the agent is obliged to surface these, and the golden set asserts
    # on them directly rather than trusting a judge to notice.
    caveats: list[str] = field(default_factory=list)
    # Extra structured fields per rule (target_minutes, elapsed_minutes, ...).
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "amount_inr": self.amount_inr,
            "override_applied": self.override_applied,
            "governing_source": self.governing_source,
            "sources": self.sources,
            "confidence": self.confidence,
            "caveats": self.caveats,
            "working": self.working,
            **self.detail,
        }


def _fmt(ts: dt.datetime, tz: dt.tzinfo | None) -> str:
    """Render a timestamp in the DATASET's timezone, not the database session's.

    Postgres hands back timestamptz in the session zone (UTC here), so a
    booking the workbook records as 09:00 IST prints as 03:30+00:00. The
    instant is correct and the arithmetic is unaffected, but `working` is shown
    to a support agent who will compare it against the source document. A line
    that disagrees with the document destroys trust in the number beside it, so
    every timestamp in `working` is rendered in the snapshot's zone.
    """
    return ts.astimezone(tz).isoformat() if tz else ts.isoformat()


def _num(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


# ---------------------------------------------------------------------------
# Rule 1: cancellation fee
# ---------------------------------------------------------------------------

# Carriers whose pickup confirmation can lag behind physical collection. KI-211
# makes this verdict-changing rather than cosmetic, so it is data, not prose.
_LAGGING_PICKUP_CARRIERS = {"swiftship": "KI-211"}


def evaluate_cancellation(
    order: dict[str, Any],
    terms: TermSet,
    snapshot_time: dt.datetime,
) -> Verdict:
    """Can this order be cancelled, and does a fee apply?

    NOTE ON THE CLOCK (assumption A1). The build spec computed
    `pickup_due_at - snapshot_time`, but SOP v4 measures the free window from
    BOOKING -- "No fee within 30 minutes of booking" -- and the workbook has no
    `pickup_due_at` column at all. So the window runs
    `booked_at -> cancellation_requested_at`, falling back to the snapshot when
    no cancellation has actually been requested (the hypothetical "can I cancel
    this now?").
    """
    status = (order.get("status") or "").upper()
    tz = snapshot_time.tzinfo
    working = [f"snapshot_time = {_fmt(snapshot_time, tz)}", f"status = {status}"]
    sources: list[str] = []

    if status == "DELIVERED":
        term = terms.resolve("cancellation.delivered_allowed", required=False)
        if term:
            sources.append(term.doc_id)
        working.append("DELIVERED orders cannot be cancelled")
        return Verdict(
            rule="cancellation_fee", outcome="not_cancellable",
            reason_code="delivered", working=working,
            governing_source=term.doc_id if term else None, sources=sources,
        )

    if status == "PICKED_UP":
        term = terms.resolve("cancellation.picked_up_allowed", required=False)
        if term:
            sources.append(term.doc_id)
        actual = order.get("pickup_actual_at")
        if actual:
            working.append(f"pickup_actual_at = {_fmt(actual, tz)}")
        working.append("already picked up; return-to-origin applies instead")
        return Verdict(
            rule="cancellation_fee", outcome="not_cancellable",
            reason_code="picked_up", working=working,
            governing_source=term.doc_id if term else None,
            override_applied=bool(term and term.is_contract), sources=sources,
        )

    if status == "DRAFT":
        term = terms.resolve("cancellation.draft_fee_inr", required=False)
        if term:
            sources.append(term.doc_id)
        working.append("DRAFT orders cancel with no fee")
        return Verdict(
            rule="cancellation_fee", outcome="no_fee", reason_code="draft",
            amount_inr=0.0, working=working,
            governing_source=term.doc_id if term else None, sources=sources,
        )

    if status != "BOOKED":
        return Verdict(
            rule="cancellation_fee", outcome="undecidable",
            reason_code="facts_missing",
            working=working + [f"unrecognised order status {status!r}"],
            confidence="low",
        )

    # --- BOOKED, not yet picked up -----------------------------------------
    booked_at = order.get("booked_at")
    if booked_at is None:
        return Verdict(
            rule="cancellation_fee", outcome="undecidable",
            reason_code="facts_missing",
            working=working + ["booked_at is missing; cannot measure the free window"],
            confidence="low",
        )

    requested_at = order.get("cancellation_requested_at") or snapshot_time
    used_snapshot = order.get("cancellation_requested_at") is None
    elapsed_minutes = (requested_at - booked_at).total_seconds() / 60

    working.append(f"booked_at = {_fmt(booked_at, tz)}")
    working.append(
        f"cancellation_requested_at = {_fmt(requested_at, tz)}"
        + (" (no request on record; using snapshot_time)" if used_snapshot else "")
    )
    working.append(f"elapsed_since_booking = {elapsed_minutes:.0f} minutes")

    # KI-211: a lagging carrier may already have collected the parcel while the
    # record still says BOOKED. That would make the answer return-to-origin
    # instead of "no fee", so it is recorded as a verdict-inverting caveat.
    caveats: list[str] = []
    carrier = (order.get("carrier") or "").strip().lower()
    known_issue = _LAGGING_PICKUP_CARRIERS.get(carrier)
    window_end = order.get("pickup_window_end")
    if known_issue and order.get("pickup_actual_at") is None:
        if order.get("pickup_window_start") and snapshot_time >= order["pickup_window_start"]:
            caveats.append(known_issue)
            working.append(
                f"{order.get('carrier')} pickup confirmation can lag ({known_issue}); "
                f"the parcel may already be collected despite status BOOKED"
            )

    # A contract waiver beats the SOP window outright.
    waiver = terms.resolve("cancellation.fee_waived", required=False)
    if waiver is not None and waiver.value is True and waiver.is_contract:
        sources.append(waiver.doc_id)
        window = terms.resolve("cancellation.free_window_minutes", required=False)
        if window:
            sources.append(window.doc_id)
            working.append(
                f"general SOP would charge after {_num(window.value):.0f} minutes"
            )
        working.append(
            f"{waiver.doc_id} waives the cancellation fee regardless of elapsed time"
        )
        return Verdict(
            rule="cancellation_fee", outcome="no_fee",
            reason_code="contract_waiver", amount_inr=0.0,
            override_applied=True, governing_source=waiver.doc_id,
            sources=sources, working=working, caveats=caveats,
        )

    window = terms.resolve("cancellation.free_window_minutes", required=False)
    fee = terms.resolve("cancellation.fee_after_window_inr", required=False)
    if window is None or fee is None:
        return Verdict(
            rule="cancellation_fee", outcome="undecidable",
            reason_code="facts_missing",
            working=working + ["no cancellation window/fee term available"],
            confidence="low", caveats=caveats,
        )

    sources.extend([window.doc_id, fee.doc_id])
    window_minutes = _num(window.value)
    working.append(f"free_cancellation_window = {window_minutes:.0f} minutes")

    if elapsed_minutes <= window_minutes:
        working.append("within the free window, so no fee applies")
        return Verdict(
            rule="cancellation_fee", outcome="no_fee",
            reason_code="within_free_window", amount_inr=0.0,
            override_applied=False, governing_source=window.doc_id,
            sources=sources, working=working, caveats=caveats,
        )

    amount = _num(fee.value)
    working.append(f"past the free window, so a fee of INR {amount:.0f} applies")
    return Verdict(
        rule="cancellation_fee", outcome="fee_applies",
        reason_code="after_window", amount_inr=amount,
        override_applied=False, governing_source=fee.doc_id,
        sources=sources, working=working, caveats=caveats,
    )


# ---------------------------------------------------------------------------
# Rule 2: failed-pickup service credit
# ---------------------------------------------------------------------------

def evaluate_service_credit(
    terms: TermSet,
    snapshot_time: dt.datetime,
    order: dict[str, Any] | None = None,
    stated_facts: dict[str, Any] | None = None,
) -> Verdict:
    """Is a failed-pickup credit owed, and how much?

    Facts come either from an order record or from `stated_facts` (the
    "a pickup was 3 hours late" style question). Unknown fault is UNDECIDABLE,
    not "no": the SOP says explicitly not to promise a credit when carrier
    fault, pickup timing, or customer fault is unknown.
    """
    facts = dict(stated_facts or {})
    tz = snapshot_time.tzinfo
    working = [f"snapshot_time = {_fmt(snapshot_time, tz)}"]
    sources: list[str] = []

    delay_hours: float | None = None
    carrier_fault = facts.get("carrier_fault")
    customer_fault = facts.get("customer_fault")
    fee: float | None = None

    if facts.get("delay_hours") is not None:
        delay_hours = float(facts["delay_hours"])
        working.append(f"stated delay = {delay_hours:.2f} hours")

    if order:
        window_end = order.get("pickup_window_end")
        actual = order.get("pickup_actual_at")
        if window_end is not None and delay_hours is None:
            reference = actual or snapshot_time
            delay_hours = (reference - window_end).total_seconds() / 3600
            working.append(f"pickup_window_end = {_fmt(window_end, tz)}")
            working.append(
                f"pickup {'actual' if actual else 'still outstanding at snapshot'} = "
                f"{_fmt(reference, tz)}"
            )
            working.append(f"delay_past_window_end = {delay_hours:.2f} hours")
        if carrier_fault is None:
            carrier_fault = order.get("carrier_fault")
        if customer_fault is None:
            customer_fault = order.get("customer_fault")
        if order.get("shipment_fee_inr") is not None:
            fee = _num(order["shipment_fee_inr"])

    if facts.get("shipment_fee_inr") is not None:
        fee = float(facts["shipment_fee_inr"])

    # The SOP forbids promising a credit on unknown facts.
    if delay_hours is None or carrier_fault is None or customer_fault is None:
        missing = [
            name for name, value in
            (("pickup timing", delay_hours), ("carrier fault", carrier_fault),
             ("customer fault", customer_fault))
            if value is None
        ]
        guard = terms.resolve("service_credit.undecidable_when_facts_unknown",
                              required=False)
        if guard:
            sources.append(guard.doc_id)
        working.append(f"unknown: {', '.join(missing)}")
        return Verdict(
            rule="service_credit", outcome="undecidable",
            reason_code="facts_unknown", working=working,
            governing_source=guard.doc_id if guard else None,
            sources=sources, confidence="low",
        )

    threshold = terms.resolve("service_credit.delay_threshold_hours")
    sources.append(threshold.doc_id)
    threshold_hours = _num(threshold.value)
    override = threshold.is_contract
    working.append(
        f"credit threshold = {threshold_hours:.0f} hours ({threshold.doc_id})"
    )

    if not carrier_fault:
        return Verdict(
            rule="service_credit", outcome="not_eligible",
            reason_code="no_carrier_fault",
            working=working + ["carrier is not at fault"],
            override_applied=override, governing_source=threshold.doc_id,
            sources=sources,
        )

    if customer_fault:
        return Verdict(
            rule="service_credit", outcome="not_eligible",
            reason_code="customer_fault",
            working=working + ["a customer-caused issue is recorded"],
            override_applied=override, governing_source=threshold.doc_id,
            sources=sources,
        )

    if delay_hours <= threshold_hours:
        working.append(
            f"delay {delay_hours:.2f}h does not exceed the {threshold_hours:.0f}h threshold"
        )
        return Verdict(
            rule="service_credit", outcome="not_eligible",
            reason_code="below_threshold", working=working,
            override_applied=override, governing_source=threshold.doc_id,
            sources=sources,
        )

    # Eligible. A contract may replace the amount outright; otherwise the SOP's
    # lower-of-cap-or-percentage applies.
    fixed = terms.resolve("service_credit.fixed_amount_inr", required=False)
    if fixed is not None and fixed.is_contract:
        amount = _num(fixed.value)
        sources.append(fixed.doc_id)
        working.append(
            f"{fixed.doc_id} sets a fixed credit of INR {amount:.0f}, replacing "
            f"the SOP amount"
        )
        governing = fixed.doc_id
        override = True
    else:
        cap = terms.resolve("service_credit.amount_cap_inr")
        pct = terms.resolve("service_credit.amount_pct_of_fee")
        sources.extend([cap.doc_id, pct.doc_id])
        if fee is None:
            return Verdict(
                rule="service_credit", outcome="undecidable",
                reason_code="facts_unknown",
                working=working + ["shipment fee unknown; cannot compute 10% branch"],
                sources=sources, confidence="low",
            )
        cap_value = _num(cap.value)
        pct_value = _num(pct.value)
        percentage = fee * pct_value / 100
        amount = min(cap_value, percentage)
        working.append(f"shipment_fee = INR {fee:.0f}")
        working.append(
            f"credit = lower of INR {cap_value:.0f} and {pct_value:.0f}% "
            f"(INR {percentage:.0f}) = INR {amount:.0f}"
        )
        governing = cap.doc_id

    approval = terms.resolve("service_credit.manager_approval_above_inr",
                             required=False)
    needs_approval = False
    if approval is not None:
        sources.append(approval.doc_id)
        needs_approval = amount > _num(approval.value)
        if needs_approval:
            working.append(
                f"exceeds INR {_num(approval.value):.0f}, so manager approval is required"
            )

    detail: dict[str, Any] = {"requires_manager_approval": needs_approval}

    # A10: the aggregate cap is stated but not enforceable -- no credits ledger
    # exists, so remaining headroom is unknowable. Say so rather than imply it
    # was checked.
    aggregate = terms.resolve("service_credit.monthly_aggregate_cap_inr",
                              required=False)
    if aggregate is not None:
        sources.append(aggregate.doc_id)
        detail["monthly_aggregate_cap_inr"] = _num(aggregate.value)
        working.append(
            f"note: a monthly aggregate cap of INR {_num(aggregate.value):.0f} "
            f"applies, but credits already issued this month are not tracked in "
            f"the available data, so remaining headroom cannot be confirmed"
        )

    return Verdict(
        rule="service_credit", outcome="eligible", reason_code="threshold_met",
        amount_inr=amount, override_applied=override,
        governing_source=governing, sources=sources, working=working,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Rule 3: SLA status
# ---------------------------------------------------------------------------

_MINUTES = {
    "minutes": 1.0,
    "hours": 60.0,
    "business_hours": 60.0,
    "business_days": 540.0,   # 9 business hours; see assumption A3
}


def evaluate_sla(
    ticket: dict[str, Any],
    terms: TermSet,
    snapshot_time: dt.datetime,
) -> Verdict:
    """Is this ticket's first-response target met, at risk, or breached?

    Severity is DERIVED, not read (assumption A4), so the verdict carries the
    derivation and its rationale. An unclassifiable ticket is undecidable
    rather than assigned a default, because guessing moves the target between
    15 minutes and 8 business hours.

    Boundary convention (A11): elapsed > target is breached; elapsed == target
    is `at_target`, which is a distinct outcome so the edge is visible.
    """
    tz = snapshot_time.tzinfo
    working = [f"snapshot_time = {_fmt(snapshot_time, tz)}"]
    severity = ticket.get("derived_severity")
    rationale = ticket.get("severity_rationale") or ""

    if not severity:
        return Verdict(
            rule="sla_status", outcome="undecidable",
            reason_code="severity_underivable",
            working=working + [rationale or "severity could not be derived"],
            confidence="low",
            detail={"severity_derived": None, "severity_rationale": rationale},
        )

    created_at = ticket.get("created_at")
    if created_at is None:
        return Verdict(
            rule="sla_status", outcome="undecidable", reason_code="facts_missing",
            working=working + ["ticket has no created_at"], confidence="low",
            detail={"severity_derived": severity},
        )

    target = terms.resolve_sla_target(severity)
    unit = target.unit or "minutes"
    target_minutes = _num(target.value) * _MINUTES.get(unit, 1.0)

    # A8: no first-response timestamp exists, so an open ticket is treated as
    # still awaiting first response.
    elapsed_minutes = (snapshot_time - created_at).total_seconds() / 60

    working.append(f"derived_severity = {severity} ({rationale})")
    working.append(f"created_at = {_fmt(created_at, tz)}")
    working.append(f"elapsed = {elapsed_minutes:.0f} minutes")
    working.append(
        f"target = {_num(target.value):g} {unit} = {target_minutes:.0f} minutes "
        f"({target.doc_id})"
    )
    if target.override_applied:
        working.append(
            f"{target.doc_id} replaces the general support-policy target"
        )

    if elapsed_minutes > target_minutes:
        outcome, reason = "breached", "past_target"
        working.append(
            f"breached by {elapsed_minutes - target_minutes:.0f} minutes"
        )
    elif elapsed_minutes == target_minutes:
        outcome, reason = "at_target", "exactly_at_target"
        working.append("exactly at target; not breached")
    else:
        outcome, reason = "within_target", "inside_target"
        working.append(
            f"{target_minutes - elapsed_minutes:.0f} minutes remaining"
        )

    return Verdict(
        rule="sla_status", outcome=outcome, reason_code=reason,
        override_applied=target.override_applied,
        governing_source=target.doc_id, sources=[target.doc_id],
        working=working,
        detail={
            "target_minutes": round(target_minutes),
            "elapsed_minutes": round(elapsed_minutes),
            "severity_derived": severity,
            "severity_rationale": rationale,
        },
    )
