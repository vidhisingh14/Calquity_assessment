# ParcelPilot — Architecture Note

## Layer diagram

```
api  ->  auth, agent
agent  ->  tools, services, llm, observability
tools  ->  services, repositories, auth (read-only checks)
services  ->  repositories
repositories  ->  db
```

Enforced by `backend/scripts/check_layers.py`, run as a pytest test
(`test_layer_boundaries.py`) so a violation fails the build rather than
relying on discipline. It caught a real violation during development
(`routes_health.py` importing repositories directly) before any review saw it.

One documented carve-out: `app.llm.embeddings` is reachable from `tools/` and
`services/`, but `app.llm.client` (the chat model) is not. The rule's purpose
is that tools and services must not *reason* — an embedding is deterministic
vectorisation, not a decision.

## The agent loop

Hand-rolled (`app/agent/loop.py`), not framework-based. Eight-step budget.
Each turn: build messages → call the chat model with tool schemas → for each
tool call, validate args, run the tool, append the result → repeat until the
model stops calling tools or a `requires_confirmation` tool fires, which
breaks the loop so nothing writes without the user seeing the draft first.

Budget exhaustion is a signal, not a crash: the turn returns what it has, says
the chain was cut short, and offers escalation.

## Tool table

| Tool | Input | Output | Confirmation |
|---|---|---|---|
| `lookup_records` | entity, record_id/filters | rows, scoped, tier-4 fields marked context-only | No |
| `search_documents` | query, doc_types, include_deprecated | ranked chunks, conflicts, excluded | No |
| `evaluate_policy` | rule, order_id/ticket_id, stated_facts | structured verdict (outcome, reason_code, amount, override_applied, caveats, working) | No |
| `create_escalation` | summary, reason, severity | pending_action token (prepare only) | **Yes** |

## Authority ladder

Defined once in `documents.authority_tier` (1 contract → 5 deprecated), never
re-implemented. Enforced in three independent places:

1. **Retrieval** (`services/retrieval.py`): a reserved-slot pass fetches the
   caller's own tier-1 contract so it cannot be crowded out by generic policy
   on raw similarity; a relevance floor stops an irrelevant contract clause
   topping the context merely for being tier 1; a stable sort on
   `(bucket, score)` makes the override a guarantee, not a heuristic. Every
   promotion is logged.
2. **Terms** (`app/repositories/terms_repo.py`): `lookup_terms` hard-codes
   `authority_tier < 5` in SQL with no parameter that relaxes it. Deprecated
   terms are reachable only through a separately named function used for the
   internal version-comparison case.
3. **Validator** (`app/agent/validator.py`): a tier-5 citation is a hard block,
   not a downgrade.

## Conflict handling

`services/conflict.py` reduces chunks to claim tuples (subject, value, unit)
against a small lexicon, compares across documents, and lets tier decide the
winner. Equal-tier disagreement is unresolved and escalates. Subjects outside
the lexicon are logged, not silently dropped — a named coverage limit, not a
surprise.

## Trust layer (validator)

Eight checks, run after the draft and before the user sees it: scope leak
(hard block), deprecated citation (hard block), citation existence, context-only
citation, ungrounded numbers, unresolved conflict, undecidable-answered-
confidently, and caveat omission. Confidence is *derived* from these flags plus
top source tier — never asked of the model.

The ungrounded-numbers check strips timestamps, ids, and section references
before comparing, because a correct answer quoting a tool-returned timestamp
should never be downgraded. A trust signal that cries wolf gets ignored, which
costs more than the check gains.

## Data and timezone handling

The dataset's timestamp hazard is **not** Excel serial dates (the spec's
predicted failure) — every value in the real workbook is already a string.
The actual hazard is that those strings are timezone-naive while the README
snapshot carries an explicit zone (`Asia/Kolkata`). A naive-as-UTC misread
shifts every calculation 5.5 hours, which is enough to invert a verdict
(ORD-2002's 4h30m delay against a 4h threshold reads as −1h). Ingestion
localises every timestamp to the snapshot's zone and asserts none survive
naive; `policy_engine.py` renders every `working` timestamp back in that same
zone so a support agent's audit trail matches the source document.

## Major trade-offs

1. **Hand-rolled loop over a framework.** Every step is inspectable, and
   `on_step` callbacks drive real SSE streaming without adapting a framework's
   internals.
2. **Hybrid retrieval over vector-only.** RRF fusion plus a reserved-slot
   contract pass makes the authority guarantee possible; vector-only cannot
   express "always consider this document."
3. **Rules-first conflict and signal detection.** Detection is deterministic;
   only the one-line naming step touches a model, so re-runs never reshuffle
   what the ops team sees.
4. **Curated `doc_terms` over model extraction at answer time.**
   `data/terms_overrides.yaml` is the source of truth; ingestion *verifies*
   each declared value against its source chunk and fails the build if a
   quote doesn't match, rather than letting a parsing bug produce a silently
   wrong number.
5. **Deterministic tier-bucket promotion over score weighting.** A multiplier
   only makes an override *likely*; the stable sort makes it certain.
6. **Cerebras + Gemini split, with an honest note on what didn't work.** See
   `docs/decisions/0001-gemini-quota-and-spike-gate.md` — Cerebras is
   unusable on the provided key (402, not a capability issue), and Gemini's
   free tier caps at ~20 requests/day/model, which blocked a full 10-run spike
   and a full 32-question eval from completing in one session. The fixes
   required to make Gemini tool calling work at all (schema sanitisation,
   verbatim turn replay for `thought_signature`, 429 backoff) are permanent,
   not spike scaffolding, and are proven by a 100%-passing Phase 5 acceptance
   test and a 7-signal real detection run.

## Chunking note

Chunk size is measured with `tiktoken` purely as a deterministic ruler, not
the serving model's tokenizer (Cerebras and Gemini each tokenize differently),
so chunk sizes are approximate by design. Splitting is heading-driven rather
than purely size-driven: every document in this pack is short enough that a
pure size-based packer produced one chunk per document with no section path,
which degraded citations, conflict detection, and retrieval precision all at
once. A numbered heading always starts a new chunk regardless of token count.
