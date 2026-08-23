"""Validator checks, and specifically its FALSE POSITIVES.

A trust feature that cries wolf is worse than no trust feature: once a correct
answer gets marked low-confidence for quoting a timestamp, people stop reading
the confidence field at all. So the false-positive cases are tested as
deliberately as the true-positive ones.
"""

from __future__ import annotations

from app.agent import validator


def _sources(*specs):
    return [{"doc_id": d, "tier": t, "chunk_id": i, "account_scope": s}
            for i, (d, t, s) in enumerate(specs)]


def test_timestamps_and_ids_do_not_count_as_ungrounded_numbers():
    """The regression this test exists for.

    The answer quotes a timestamp, a section, and a known-issue id, all of
    which the tools returned. None are claims, and none may downgrade
    confidence.
    """
    answer = (
        "Booked at 2026-08-16T09:00:00+05:30, cancelled at 09:00. "
        "Per contract_northstar Section 2 and known issue KI-211, no fee applies."
    )
    verdict = {"rule": "cancellation_fee", "outcome": "no_fee",
               "amount_inr": 0.0, "caveats": ["KI-211"],
               "working": ["elapsed_since_booking = 120 minutes"]}

    result = validator.validate(
        answer=answer, question="Can I cancel ORD-1001?",
        sources=_sources(("contract_northstar", 1, "ACCT-001")),
        verdicts=[verdict], conflicts=[], steps=[], account_scope="ACCT-001",
    )

    flags = {f["check"] for f in result.flags}
    assert "ungrounded_numbers" not in flags, result.flags
    assert result.confidence == "high"


def test_source_file_contains_no_control_characters():
    """A literal backspace byte inside a regex is invisible in every editor
    view and silently disables the pattern around it. This caught exactly that
    once already."""
    import pathlib

    path = pathlib.Path(validator.__file__)
    raw = path.read_bytes()
    for bad in (b"\x08", b"\x0c", b"\x0b", b"\x00"):
        assert bad not in raw, f"control byte {bad!r} in {path.name}"


def test_genuinely_invented_number_is_flagged():
    """The check must still fire on a number no tool produced."""
    result = validator.validate(
        answer="A fee of INR 777 applies.",
        question="What fee applies?",
        sources=_sources(("sop_v4", 3, None)),
        verdicts=[{"outcome": "fee_applies", "amount_inr": 250,
                   "working": ["fee = INR 250"]}],
        conflicts=[], steps=[], account_scope=None,
    )
    flags = {f["check"] for f in result.flags}
    assert "ungrounded_numbers" in flags
    assert result.confidence == "low"


def test_user_supplied_numbers_are_grounded():
    """'three hours late' in the question must not trip the check."""
    result = validator.validate(
        answer="A 3 hour delay does not meet the 4 hour threshold.",
        question="A pickup was 3 hours late. Do I get a credit?",
        sources=_sources(("contract_lumenworks", 1, "ACCT-002")),
        verdicts=[{"outcome": "not_eligible",
                   "working": ["credit threshold = 4 hours"]}],
        conflicts=[], steps=[], account_scope="ACCT-002",
    )
    assert "ungrounded_numbers" not in {f["check"] for f in result.flags}


def test_scope_leak_hard_blocks():
    result = validator.validate(
        answer="Northstar may cancel free of charge.",
        question="What are Northstar's terms?",
        sources=_sources(("contract_northstar", 1, "ACCT-001")),
        verdicts=[], conflicts=[], steps=[], account_scope="ACCT-002",
    )
    assert result.blocked is True
    assert result.confidence == "low"
    assert "logged for review" in result.answer


def test_deprecated_citation_blocks():
    result = validator.validate(
        answer="The Enterprise P1 target is 1 hour.",
        question="What is the P1 target?",
        sources=_sources(("policy_v2", 5, None)),
        verdicts=[], conflicts=[], steps=[], account_scope=None,
    )
    assert result.blocked is True
    assert result.escalation_offered is True


def test_omitted_caveat_is_flagged():
    """A2: KI-211 can invert the verdict, so omitting it is a defect."""
    result = validator.validate(
        answer="No fee applies.",
        question="Can I cancel ORD-1001?",
        sources=_sources(("contract_northstar", 1, "ACCT-001")),
        verdicts=[{"outcome": "no_fee", "caveats": ["KI-211"], "working": []}],
        conflicts=[], steps=[], account_scope="ACCT-001",
    )
    assert "caveat_omitted" in {f["check"] for f in result.flags}
    assert result.confidence == "medium"


def test_undecidable_answered_confidently_is_flagged():
    result = validator.validate(
        answer="Yes, you are definitely owed a credit.",
        question="Am I owed a credit?",
        sources=_sources(("sop_v4", 3, None)),
        verdicts=[{"outcome": "undecidable", "working": []}],
        conflicts=[], steps=[], account_scope=None,
    )
    flags = {f["check"] for f in result.flags}
    assert "undecidable_answered_confidently" in flags
    assert result.escalation_offered is True


def test_confidence_is_derived_from_top_tier():
    """Never asked of the model. A tier-3-only answer caps at medium."""
    result = validator.validate(
        answer="The SOP says no fee within 30 minutes.",
        question="What is the window?",
        sources=_sources(("sop_v4", 3, None)),
        verdicts=[{"outcome": "no_fee", "working": ["window = 30 minutes"]}],
        conflicts=[], steps=[], account_scope=None,
    )
    assert result.confidence == "medium"
