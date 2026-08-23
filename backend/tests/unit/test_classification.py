"""Derived ticket severity (assumption A4).

Severity is not in the data, so it is inferred -- which makes it the weakest
link in every SLA answer. These tests pin the inference to the severity
definitions in Support Policy v3 section 2, and pin the behaviour that matters
most: when nothing matches confidently, the answer is None, not a guess.

Note what is NOT asserted here: TKT-504's severity. It is genuinely arguable
between P2 and P3, so per the A4 sign-off no golden question and no test
depends on it.
"""

from __future__ import annotations

from app.services.classification import classify_ticket


def test_complete_outage_is_p1():
    result = classify_ticket(
        "All shipment creation is failing",
        "Every user at Northstar gets HTTP 500 when creating any shipment. "
        "Existing shipments can still be viewed.",
    )
    assert result.severity == "P1"
    assert "shipment creation" in result.rationale
    assert result.issue_type == "outage"


def test_suspected_credential_exposure_is_p1():
    """Policy v3 lists 'suspected credential exposure' as P1 in its own right,
    with no outage required."""
    result = classify_ticket(
        "Possible API key exposure",
        "An employee accidentally posted a screenshot containing a production "
        "API key in a public channel.",
    )
    assert result.severity == "P1"
    assert result.issue_type == "security"


def test_degraded_feature_with_workaround_is_p2():
    result = classify_ticket(
        "Bulk upload fails for 4,200-row CSV",
        "The CSV reaches roughly 70% and fails. Creating shipments one-by-one "
        "still works.",
    )
    assert result.severity == "P2"
    assert "workaround" in result.rationale
    assert result.issue_type == "bulk_upload"


def test_how_to_question_is_p3():
    result = classify_ticket(
        "How do we change the billing contact?",
        "Customer wants to replace the billing-contact email on their account.",
    )
    assert result.severity == "P3"
    assert result.issue_type == "account_admin"


def test_unmatched_ticket_returns_none_rather_than_guessing():
    """None flows to undecidable and then to a human.

    Guessing would silently move a target from 15 minutes to 8 business hours,
    which is the difference between breached and comfortable.
    """
    result = classify_ticket("Quarterly review", "Scheduling a call next month.")
    assert result.severity is None
    assert "human" in result.rationale


def test_empty_input_is_not_classified():
    result = classify_ticket(None, None)
    assert result.severity is None


def test_every_classification_carries_a_rationale():
    """The rationale is not decoration: every SLA answer must state inline how
    the severity was derived, so it has to exist for every outcome."""
    cases = [
        ("All shipment creation is failing", "Every user gets HTTP 500."),
        ("Bulk upload fails", "Still works one-by-one."),
        ("How do we change the billing contact?", ""),
        ("Quarterly review", "Scheduling a call."),
    ]
    for subject, description in cases:
        assert classify_ticket(subject, description).rationale.strip()


def test_classification_is_deterministic():
    """A board that reshuffles between runs stops being trusted within a week."""
    args = ("Bulk upload fails for 4,200-row CSV", "Creating one-by-one still works.")
    assert len({classify_ticket(*args).severity for _ in range(20)}) == 1
