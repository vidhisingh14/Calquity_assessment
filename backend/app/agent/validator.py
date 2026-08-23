"""Post-answer trust checks. Runs after the draft, before the user sees it.

Confidence is DERIVED from these flags plus the top source tier. It is never
asked of the model: a self-reported confidence score is close to meaningless,
a derived one is auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Numbers that are never "ungrounded": ordinals, years, and the small integers
# that show up in ordinary prose.
_NUMBER = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
_ALWAYS_ALLOWED = {"1", "2", "3", "4", "5", "10", "24", "7", "2026", "0", "100"}

# Timestamps, dates and identifiers fragment into meaningless digits ("09:00"
# yields 09 and 00; "Section 2" yields 2), so they are stripped before the
# grounding check. A CORRECT answer downgraded for quoting a time the tool
# itself returned teaches people to ignore the confidence signal, which
# costs more than the check gains.
_TIMESTAMPISH = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]?[\d:+\-]*"
    r"|\d{1,2}:\d{2}(?::\d{2})?"
    r"|sections?\s+\d+(?:\.\d+)?"
    r"|KI-\d+|(?:ORD|TKT|ACCT)-\d+"
    r"|v\d+",
    re.I,
)


@dataclass
class ValidationResult:
    flags: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = "high"
    blocked: bool = False
    escalation_offered: bool = False
    answer: str = ""

    def flag(self, name: str, detail: str, severity: str = "warn") -> None:
        self.flags.append({"check": name, "detail": detail, "severity": severity})


def _normalise(raw: str) -> str:
    """Compare numbers by value, not by spelling: 09 == 9, 250.0 == 250."""
    cleaned = raw.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        return cleaned
    return str(int(value)) if value == int(value) else str(value)


def _numbers_in(text: str, strip_timestamps: bool = False) -> set[str]:
    if strip_timestamps:
        text = _TIMESTAMPISH.sub(" ", text or "")
    return {_normalise(m.group(0)) for m in _NUMBER.finditer(text or "")}


def validate(
    answer: str,
    question: str,
    sources: list[dict[str, Any]],
    verdicts: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    steps: list[Any],
    account_scope: str | None,
) -> ValidationResult:
    result = ValidationResult(answer=answer)
    cited_docs = {s.get("doc_id") for s in sources if s.get("doc_id")}
    tiers = [s.get("tier") for s in sources if s.get("tier") is not None]
    top_tier = min(tiers) if tiers else None

    # 1. Scope leak. HARD BLOCK -- this is an incident, not a downgrade.
    leaked = [
        s for s in sources
        if s.get("account_scope") not in (None, account_scope)
    ]
    if leaked:
        result.flag(
            "scope_leak",
            f"sources outside caller scope: {[s.get('doc_id') for s in leaked]}",
            severity="block",
        )
        result.blocked = True
        result.confidence = "low"
        result.answer = (
            "I could not complete that request. This has been logged for review."
        )
        return result

    # 2. Deprecated citation. Blocks and escalates.
    deprecated = [s.get("doc_id") for s in sources if s.get("tier") == 5]
    if deprecated:
        result.flag("deprecated_citation",
                    f"tier-5 sources cited: {deprecated}", severity="block")
        result.blocked = True
        result.confidence = "low"
        result.escalation_offered = True
        return result

    # 3. Citation existence: every doc_id named in the answer must have been
    # returned by a tool this turn.
    mentioned = set(re.findall(r"\b(?:policy_v\d|sop_v\d|product_guide|contract_\w+)\b",
                               answer or ""))
    invented = mentioned - cited_docs
    if invented:
        result.flag("citation_existence",
                    f"answer cites sources no tool returned: {sorted(invented)}")
        result.confidence = "low"

    # 4. Context-only citation: a ticket id presented as the basis for a rule.
    if re.search(r"\bTKT-\d+\b.*\b(polic|rule|per|according)", answer or "", re.I):
        result.flag("context_only_citation",
                    "answer appears to source a rule from a ticket resolution")
        result.confidence = "low"
        result.escalation_offered = True

    # 5. Ungrounded numbers. Grounding set = tool results + verdict working +
    # numbers the user themselves supplied, so "three hours late" in the
    # question never trips it.
    grounded = set(_ALWAYS_ALLOWED) | _numbers_in(question)
    for verdict in verdicts:
        grounded |= _numbers_in(" ".join(verdict.get("working", [])))
        for key in ("amount_inr", "target_minutes", "elapsed_minutes"):
            if verdict.get(key) is not None:
                grounded.add(str(verdict[key]).rstrip("0").rstrip(".")
                             if isinstance(verdict[key], float) else str(verdict[key]))
                grounded.add(str(int(verdict[key])) if isinstance(
                    verdict[key], (int, float)) else str(verdict[key]))
    for step in steps:
        grounded |= _numbers_in(str(getattr(step, "raw_result", "")))

    grounded = {_normalise(g) for g in grounded}
    ungrounded = {
        n for n in _numbers_in(answer, strip_timestamps=True) if n not in grounded
    }
    if ungrounded:
        result.flag("ungrounded_numbers",
                    f"numbers not traceable to a tool result: {sorted(ungrounded)}")
        result.confidence = "low"

    # 6. Unresolved conflict not mentioned.
    unresolved = [c for c in conflicts if not c.get("resolved", True)]
    if unresolved and "conflict" not in (answer or "").lower():
        result.flag("unresolved_conflict",
                    "equal-authority conflict not surfaced in the answer")
        result.confidence = _downgrade(result.confidence, "medium")
        result.escalation_offered = True

    # 7. Undecidable verdict answered confidently.
    undecidable = [v for v in verdicts if v.get("outcome") == "undecidable"]
    if undecidable:
        result.escalation_offered = True
        if not re.search(r"cannot|unable|not able|unknown|escalat", answer or "", re.I):
            result.flag("undecidable_answered_confidently",
                        "policy engine returned undecidable but the answer is confident")
            result.confidence = "low"

    # 8. A verdict-inverting caveat must actually appear in the answer.
    for verdict in verdicts:
        for caveat in verdict.get("caveats", []) or []:
            if caveat.lower() not in (answer or "").lower():
                result.flag("caveat_omitted",
                            f"{caveat} can invert this verdict but is not stated")
                result.confidence = _downgrade(result.confidence, "medium")

    # Derived confidence: never asked of the model.
    if result.confidence == "high":
        if top_tier is None or top_tier > 3:
            result.confidence = "low"
            result.escalation_offered = True
        elif top_tier == 3:
            result.confidence = "medium"

    return result


def _downgrade(current: str, floor: str) -> str:
    order = {"high": 2, "medium": 1, "low": 0}
    return current if order[current] < order[floor] else floor
