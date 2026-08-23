# ADR-0002: The scope clause needs three arms, not two

**Status:** Fixed. **Date:** 2026-08-23

## Context

Build spec §8.2 gives document scope filtering as
`WHERE account_scope IS NULL OR account_scope = :scope`. `AuthContext.
account_scope_filter()` returns `None` for internal roles, meaning
*unrestricted*. Under the two-arm clause, `account_scope = NULL` is never
true in SQL, so a `None` scope matched only unscoped documents — support
agents and ops leads could never retrieve any contract. Nothing errored; the
contract simply never appeared in results, and an answer would fall back to
general policy while sounding equally confident.

Found while manually verifying vector search after re-ingesting with real
embeddings: an internal-role keyword search for Northstar's contract terms
returned zero results.

## Decision

`app/repositories/docs_repo.py`'s three queries now use:

```sql
WHERE (%(scope)s::text IS NULL          -- unrestricted (internal roles)
       OR account_scope IS NULL         -- document applies to everyone
       OR account_scope = %(scope)s)    -- document belongs to this caller
```

A customer's scope is still their own account id (never `None`), so the
customer-facing guarantee — `unscoped ∪ own account` — is unchanged.
`test_internal_role_can_retrieve_contracts` and
`test_unrestricted_scope_does_not_leak_to_customers` in
`tests/integration/test_cross_account_leak.py` pin both halves.

## Consequence

Four golden questions depended on this working (g12, g18, g28, g29). Caught
before any of them were run, by direct verification against the real
embeddings rather than trusting the fixture-seeded integration tests, which
happened not to exercise an internal role against a contract-bearing query.
