"""THE PHASE 3 GATE.

These tests must pass before any LLM code is written. Access control that is
requested in a prompt is not access control; these prove it is enforced in SQL,
where the model cannot reach it.

Every test here is adversarial in the same specific way: the caller is scoped to
one account and something -- a tool argument, a query string, an injected
instruction -- claims a different one. The scope used must always come from the
AuthContext, never from the claim.

There is also a POSITIVE control at the bottom. A scope filter tightened until
nothing ever crosses an account boundary would pass every negative test here
and break internal operations completely, so the suite must be able to fail in
both directions.
"""

from __future__ import annotations

import pytest

from app.auth import policies
from app.repositories import accounts_repo, docs_repo, orders_repo, tickets_repo


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------

def test_customer_cannot_retrieve_other_account_contract(customer_lumen):
    """A LumenWorks customer searching for Northstar's contract gets nothing.

    The scope passed to the repository comes from ctx.account_scope_filter(),
    which is derived from the resolved role -- there is no code path where a
    caller-supplied account id reaches this parameter.
    """
    scope = customer_lumen.account_scope_filter()
    results = docs_repo.keyword_search(
        query="cancellation fee waiver regardless of how long",
        tiers=policies.visible_doc_tiers(customer_lumen),
        account_scope=scope,
        k=20,
    )

    doc_ids = {r["doc_id"] for r in results}
    assert "contract_northstar" not in doc_ids
    assert all(r["account_scope"] in (None, "ACCT-002") for r in results)


def test_customer_sees_own_contract(customer_lumen):
    """The mirror of the test above: scoping must not break the legitimate case."""
    results = docs_repo.keyword_search(
        query="service credit pickup window",
        tiers=policies.visible_doc_tiers(customer_lumen),
        account_scope=customer_lumen.account_scope_filter(),
        k=20,
    )
    assert "contract_lumenworks" in {r["doc_id"] for r in results}


def test_deprecated_policy_excluded_for_customer(customer_lumen):
    """Tier 5 is not in a customer's visible tiers, so it cannot be retrieved."""
    tiers = policies.visible_doc_tiers(customer_lumen, include_deprecated=True)
    assert 5 not in tiers

    results = docs_repo.keyword_search(
        query="Enterprise P1 first response",
        tiers=tiers,
        account_scope=customer_lumen.account_scope_filter(),
        k=20,
    )
    assert "policy_v2" not in {r["doc_id"] for r in results}


def test_internal_role_may_see_deprecated_on_request(ops_lead):
    """g12: an ops_lead comparing policy versions is a legitimate need.

    This is what stops the tier-5 rule being implemented as a blanket ban.
    """
    tiers = policies.visible_doc_tiers(ops_lead, include_deprecated=True)
    assert 5 in tiers

    results = docs_repo.keyword_search(
        query="Enterprise P1 first response",
        tiers=tiers,
        account_scope=ops_lead.account_scope_filter(),
        k=20,
    )
    assert "policy_v2" in {r["doc_id"] for r in results}


def test_chunk_fetch_is_scoped(customer_lumen):
    """The source drawer must not become a way to read arbitrary chunks by id."""
    northstar_chunks = docs_repo.keyword_search(
        query="cancellation", tiers=[1], account_scope="ACCT-001", k=5
    )
    assert northstar_chunks, "seed data should contain a Northstar chunk"
    target_id = northstar_chunks[0]["chunk_id"]

    leaked = docs_repo.get_chunk(target_id, customer_lumen.account_scope_filter())
    assert leaked is None


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

def test_customer_cannot_read_other_account_order(customer_lumen):
    """Empty result, NOT a permission error.

    A 403 here would confirm the order exists, which is itself the leak. The
    answer for "someone else's order" and "no such order" must be identical.
    """
    assert orders_repo.get_order("ORD-1001", customer_lumen.account_scope_filter()) is None


def test_missing_order_and_forbidden_order_are_indistinguishable(customer_lumen):
    scope = customer_lumen.account_scope_filter()
    forbidden = orders_repo.get_order("ORD-1001", scope)   # exists, other account
    missing = orders_repo.get_order("ORD-9999", scope)     # does not exist
    assert forbidden == missing is None


def test_customer_reads_own_order(customer_lumen):
    order = orders_repo.get_order("ORD-2002", customer_lumen.account_scope_filter())
    assert order is not None
    assert order["account_id"] == "ACCT-002"


def test_list_orders_never_crosses_scope(customer_lumen):
    rows = orders_repo.list_orders(customer_lumen.account_scope_filter(), limit=100)
    assert rows, "customer should see their own orders"
    assert {r["account_id"] for r in rows} == {"ACCT-002"}


def test_customer_cannot_list_other_account_tickets(customer_lumen):
    rows = tickets_repo.list_tickets(customer_lumen.account_scope_filter(), limit=100)
    assert {r["account_id"] for r in rows} == {"ACCT-002"}
    assert "TKT-501" not in {r["ticket_id"] for r in rows}


def test_filter_argument_cannot_widen_scope(customer_lumen):
    """The model asking for another account by FILTER must not widen the scope.

    The scope clause is ANDed by the repository, so an account_id filter can
    only ever narrow. This is the SQL-level equivalent of the tool overwriting
    a model-supplied account id.
    """
    rows = tickets_repo.list_tickets(
        customer_lumen.account_scope_filter(),
        filters={"account_id": "ACCT-001"},
        limit=100,
    )
    assert rows == []


def test_unknown_filter_key_is_rejected(customer_lumen):
    """An unknown key returns the valid list rather than being silently ignored,
    so the model can correct itself instead of reasoning on a bad result."""
    with pytest.raises(ValueError) as exc:
        tickets_repo.list_tickets(
            customer_lumen.account_scope_filter(),
            filters={"account_id_or_1_eq_1": "x"},
        )
    assert "allowed" in str(exc.value)


def test_account_read_is_scoped(customer_lumen):
    assert accounts_repo.get_account("ACCT-001", customer_lumen.account_scope_filter()) is None
    assert accounts_repo.get_account("ACCT-002", customer_lumen.account_scope_filter()) is not None


# --------------------------------------------------------------------------
# Positive control
# --------------------------------------------------------------------------

def test_internal_role_may_read_across_accounts(ops_lead):
    """g32. Without this, a filter tightened to leak nothing passes everything
    above while making the product useless to the people who run it."""
    assert policies.can_read_all_accounts(ops_lead) is True

    rows = tickets_repo.list_tickets_all_accounts(limit=100)
    assert {"ACCT-001", "ACCT-002"} <= {r["account_id"] for r in rows}

    ids = {r["ticket_id"] for r in rows}
    assert {"TKT-501", "TKT-502"} <= ids


def test_customer_may_not_read_across_accounts(customer_lumen):
    assert policies.can_read_all_accounts(customer_lumen) is False
