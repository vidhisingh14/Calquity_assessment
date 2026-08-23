"""Step 3: map file name -> authority metadata. Deterministic, no LLM.

An unmatched file name RAISES. It never defaults to tier 1 or tier 2 -- a
document that silently acquires authority is the worst possible failure here.

Contract account scope is resolved against the REAL account ids loaded from the
workbook, matched by account name, and the match must be exactly one. Guessing
the scope from a file name would mean a file rename could hand one customer's
contract to another customer.
"""

from __future__ import annotations

from typing import Any

from app.errors import IngestionError

# `account_name_match` is resolved against the accounts sheet at ingest time.
AUTHORITY_MAP: dict[str, dict[str, Any]] = {
    "01_Support_Policy_v3_CURRENT.pdf": dict(
        doc_id="policy_v3", doc_type="policy", authority_tier=2,
        version_label="v3", is_current=True, effective_from="2026-05-01",
    ),
    "02_Support_Policy_v2_DEPRECATED.pdf": dict(
        doc_id="policy_v2", doc_type="policy", authority_tier=5,
        version_label="v2", is_current=False, superseded_by="policy_v3",
        effective_from="2025-01-01",
    ),
    "03_Cancellation_and_Service_Credit_SOP_v4.pdf": dict(
        doc_id="sop_v4", doc_type="sop", authority_tier=3,
        version_label="v4", is_current=True, effective_from="2026-06-15",
    ),
    "04_Product_Operations_Guide_and_Known_Issues.pdf": dict(
        doc_id="product_guide", doc_type="product_guide", authority_tier=3,
        version_label=None, is_current=True, effective_from="2026-08-14",
    ),
    "05_Northstar_Logistics_Enterprise_Agreement.pdf": dict(
        doc_id="contract_northstar", doc_type="contract", authority_tier=1,
        is_current=True, account_name_match="Northstar Logistics",
    ),
    "06_LumenWorks_Service_Agreement.pdf": dict(
        doc_id="contract_lumenworks", doc_type="contract", authority_tier=1,
        is_current=True, account_name_match="LumenWorks",
    ),
}


def stamp(file_name: str, accounts: list[dict[str, Any]]) -> dict[str, Any]:
    if file_name not in AUTHORITY_MAP:
        raise IngestionError(
            f"No authority mapping for {file_name!r}. Add it to AUTHORITY_MAP "
            f"with an explicit tier. Refusing to default -- an unmapped file "
            f"silently acquiring authority is the worst outcome here. "
            f"Known: {sorted(AUTHORITY_MAP)}"
        )

    meta = dict(AUTHORITY_MAP[file_name])
    meta.setdefault("account_scope", None)
    meta.setdefault("superseded_by", None)
    meta.setdefault("version_label", None)
    meta.setdefault("effective_from", None)
    meta["file_name"] = file_name

    name_match = meta.pop("account_name_match", None)
    if name_match is not None:
        matches = [
            a for a in accounts
            if str(a.get("account_name", "")).strip().lower() == name_match.lower()
        ]
        if len(matches) != 1:
            raise IngestionError(
                f"{file_name}: expected exactly one account named "
                f"{name_match!r}, found {len(matches)}. A contract must be "
                f"scoped to a real account id, never inferred from a filename."
            )
        meta["account_scope"] = matches[0]["account_id"]

    if meta["authority_tier"] == 1 and not meta["account_scope"]:
        raise IngestionError(
            f"{file_name}: tier-1 documents must be account scoped. An unscoped "
            f"tier-1 document would override general policy for EVERY customer."
        )

    return meta
