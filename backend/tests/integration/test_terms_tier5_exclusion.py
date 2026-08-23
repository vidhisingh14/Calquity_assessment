"""Tier-5 terms must be unreachable from the policy engine BY CONSTRUCTION.

The seed data deliberately contains a deprecated term with the SAME term_key as
a current one (`sla.first_response.Enterprise.P1`: 1 hour in v2, 30 minutes in
v3). If the exclusion were implemented as a convention rather than in the
query, this is exactly the shape that would leak -- a lookup by key that
happens to match the deprecated row.
"""

from __future__ import annotations

import inspect

from app.repositories import terms_repo

KEY = "sla.first_response.Enterprise.P1"


def test_lookup_never_returns_deprecated_terms():
    rows = terms_repo.lookup_terms([KEY], account_scope=None)
    assert rows, "the current term must still be returned"
    assert all(r["authority_tier"] < 5 for r in rows)
    assert all(r["deprecated"] is False for r in rows)
    assert "policy_v2" not in {r["doc_id"] for r in rows}


def test_lookup_returns_the_current_value_not_the_deprecated_one():
    rows = terms_repo.lookup_terms([KEY], account_scope=None)
    values = {r["doc_id"]: r["term_value"] for r in rows}
    assert values["policy_v3"] == 30      # minutes, current
    assert 1 not in values.values()       # the deprecated 1-hour value


def test_lookup_for_doc_also_excludes_deprecated():
    """Even asking for the deprecated document BY NAME returns nothing."""
    rows = terms_repo.lookup_terms_for_doc("policy_v2", [KEY], account_scope=None)
    assert rows == []


def test_deprecated_terms_reachable_only_through_the_named_function():
    """They must still be readable for the internal comparison case, or g12
    cannot be answered. The point is that it takes a differently-named
    function to do it."""
    rows = terms_repo.lookup_deprecated_terms_for_comparison([KEY])
    assert {r["doc_id"] for r in rows} == {"policy_v2"}


def test_lookup_exposes_no_parameter_that_relaxes_the_filter():
    """A comment saying 'never select tier 5' is not a control.

    This asserts the guarantee structurally: there is no argument a future
    caller could pass to make lookup_terms return a deprecated row.
    """
    params = set(inspect.signature(terms_repo.lookup_terms).parameters)
    assert params == {"term_keys", "account_scope"}

    source = inspect.getsource(terms_repo.lookup_terms)
    assert "authority_tier < 5" in source


def test_term_scope_is_enforced():
    """Account-scoped terms follow the same rule as chunks."""
    rows = terms_repo.lookup_terms([KEY], account_scope="ACCT-002")
    assert all(r["account_scope"] in (None, "ACCT-002") for r in rows)
