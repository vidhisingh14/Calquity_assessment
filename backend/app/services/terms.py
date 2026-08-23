"""Policy term resolution: ONE function per key shape, resolved by authority.

Two key shapes exist in the corpus, and that asymmetry is the whole reason this
module is separate:

    contract:  sla.first_response.P1              (already knows whose account)
    policy:    sla.first_response.Enterprise.P1   (needs the plan)

Non-SLA terms share a key across tiers on purpose, e.g.
`service_credit.delay_threshold_hours` is 2 in the SOP (tier 3) and 4 in the
LumenWorks contract (tier 1). Resolution is by TIER, so the contract wins and
`override_applied` records that it did.

Resolving in two places is how an override quietly stops working in one of
them, so everything goes through `TermSet`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.errors import PolicyUndecidable
from app.repositories import terms_repo


@dataclass(frozen=True)
class ResolvedTerm:
    key: str
    value: Any
    unit: str | None
    doc_id: str
    authority_tier: int
    source_chunk_id: int
    override_applied: bool
    enforceable: bool = True

    @property
    def is_contract(self) -> bool:
        return self.authority_tier == 1


@dataclass
class TermSet:
    """All terms visible to one caller, indexed for tier-ordered resolution."""

    account_id: str | None
    contract_doc_id: str | None
    plan: str | None
    _by_key: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def _rows(self, key: str) -> list[dict[str, Any]]:
        # terms_repo returns tier-ascending, so index 0 is the highest authority.
        return self._by_key.get(key, [])

    def resolve(self, key: str, *, required: bool = True) -> ResolvedTerm | None:
        """Highest-authority value for `key`.

        A tier-1 row means a contract overrode the general rule, which the
        answer is obliged to state.
        """
        rows = self._rows(key)
        if not rows:
            if required:
                raise PolicyUndecidable(
                    f"No term found for {key!r}. Refusing to guess a value.",
                    rule=key,
                )
            return None

        row = rows[0]
        return ResolvedTerm(
            key=key,
            value=row["term_value"],
            unit=row["unit"],
            doc_id=row["doc_id"],
            authority_tier=row["authority_tier"],
            source_chunk_id=row["source_chunk_id"],
            override_applied=row["authority_tier"] == 1,
            enforceable=row.get("enforceable", True),
        )

    def resolve_sla_target(self, severity: str) -> ResolvedTerm:
        """The two-shape resolver. See module docstring.

        1. Contract present -> `sla.first_response.{severity}` on that contract.
           Found means override_applied.
        2. Otherwise -> `sla.first_response.{plan}.{severity}` on current policy.
        3. Neither -> PolicyUndecidable. Never guess a target: the difference
           between 15 minutes and 8 business hours is the difference between
           breached and comfortable.
        """
        if severity not in ("P1", "P2", "P3"):
            raise PolicyUndecidable(
                f"Unknown severity {severity!r}; cannot select an SLA target.",
                rule="sla_status",
            )

        if self.contract_doc_id:
            contract_key = f"sla.first_response.{severity}"
            for row in self._rows(contract_key):
                if row["doc_id"] == self.contract_doc_id:
                    return ResolvedTerm(
                        key=contract_key,
                        value=row["term_value"],
                        unit=row["unit"],
                        doc_id=row["doc_id"],
                        authority_tier=row["authority_tier"],
                        source_chunk_id=row["source_chunk_id"],
                        override_applied=True,
                    )

        if not self.plan:
            raise PolicyUndecidable(
                "No contract SLA term and no plan on the account; cannot select "
                "a target.",
                rule="sla_status",
            )

        policy_key = f"sla.first_response.{self.plan}.{severity}"
        resolved = self.resolve(policy_key, required=False)
        if resolved is None:
            raise PolicyUndecidable(
                f"No SLA target for plan {self.plan!r} at severity {severity!r}.",
                rule="sla_status",
            )
        return resolved

    def all_doc_ids(self) -> set[str]:
        return {r["doc_id"] for rows in self._by_key.values() for r in rows}


# Keys the three rules need. Fetched in one query rather than per-lookup.
_RULE_KEYS = [
    "cancellation.draft_fee_inr",
    "cancellation.free_window_minutes",
    "cancellation.fee_after_window_inr",
    "cancellation.waivable_by_agreement",
    "cancellation.picked_up_allowed",
    "cancellation.delivered_allowed",
    "cancellation.fee_waived",
    "cancellation.fee_waived_ignores_window",
    "cancellation.defers_to_sop",
    "service_credit.delay_threshold_hours",
    "service_credit.requires_carrier_fault",
    "service_credit.requires_no_customer_fault",
    "service_credit.amount_cap_inr",
    "service_credit.amount_pct_of_fee",
    "service_credit.fixed_amount_inr",
    "service_credit.replaces_sop_amount_and_threshold",
    "service_credit.manager_approval_above_inr",
    "service_credit.monthly_aggregate_cap_inr",
    "service_credit.defers_to_sop",
    "service_credit.undecidable_when_facts_unknown",
    "sla.first_response.P1",
    "sla.first_response.P2",
    "sla.first_response.P3",
] + [
    f"sla.first_response.{plan}.{sev}"
    for plan in ("Enterprise", "Growth", "Standard")
    for sev in ("P1", "P2", "P3")
]


def load(
    account: dict[str, Any] | None,
    account_scope: str | None,
) -> TermSet:
    """Build a TermSet for one caller.

    Deprecated (tier-5) terms cannot appear here: `terms_repo.lookup_terms`
    excludes them in SQL and exposes no parameter to relax that.
    """
    rows = terms_repo.lookup_terms(_RULE_KEYS, account_scope=account_scope)

    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_key.setdefault(row["term_key"], []).append(row)

    return TermSet(
        account_id=(account or {}).get("account_id"),
        contract_doc_id=(account or {}).get("contract_doc_id"),
        plan=(account or {}).get("plan"),
        _by_key=by_key,
    )
