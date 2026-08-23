# ParcelPilot AI Support Agent — Design

**Date:** 2026-08-23
**Status:** Awaiting review
**Source of truth:** `parcelpilot-agent-build-spec.md` (v1.0). This document records only the *deltas*, the decisions the spec left open, and the places where the spec disagrees with the actual data pack.

---

## 0. Open questions and assumptions

Everything in this section was **inferred, not told**. Each item changes behaviour if I guessed wrong. Correct them here and the change propagates to the code, the terms file and the golden set in one pass.

### 0.1 Conflicts between the spec and the real data pack

**A1 — §9.3's cancellation formula contradicts SOP v4.**
The spec computes `hours_to_pickup = (order.pickup_due_at - snapshot_time)`. SOP v4 measures the free window from **booking**, not from pickup: *"No fee within 30 minutes of booking."* The workbook has no `pickup_due_at` at all; it has `booked_at`, `pickup_window_start`, `pickup_window_end` and `cancellation_requested_at`.

*Proposed rule:* `minutes_since_booking = cancellation_requested_at - booked_at`, falling back to `snapshot_time` when `cancellation_requested_at` is null (the hypothetical "can I cancel this now?" question).
**Needs sign-off — it changes every cancellation verdict.**

**A2 — "Before pickup" is not verifiable for SwiftShip orders.**
Northstar may cancel "any BOOKED shipment before pickup". ORD-1001 is SwiftShip, status BOOKED, no `pickup_actual_at`, and at the 11:00 snapshot it sits inside its 10:30–11:30 pickup window. KI-211 states a SwiftShip parcel may already be collected while ParcelPilot still shows BOOKED, up to 20 minutes late. So the flagship example question depends on a fact the system cannot confirm.

*Options:* (a) trust the stored status and answer plainly; (b) answer "no fee" and surface the KI-211 caveat; (c) return undecidable and escalate.
*Recommendation:* **(b)** — it demonstrates the "knows when it does not know" behaviour §1.9 rewards without refusing an answerable question.
**Needs sign-off — it changes the expected answer for the spec's headline demo.**

**A3 — "Business hours" and "business days" are never defined.**
They appear throughout policy v3 and both contracts. No working window, no timezone, no holiday calendar.
*Proposed:* config constant `BUSINESS_HOURS = Mon–Fri 09:00–18:00 Asia/Kolkata`, no holiday calendar, documented as an assumption.
Mitigating fact: every business-hours case in this dataset is comfortably inside its target, so no verdict in the golden set flips on this choice.

**A4 — Ticket severity does not exist in the data.**
§6 declares `tickets.severity`. The workbook has none. Every SLA answer depends on it, so it must be derived from `subject` + `description` against policy v3 §2.
*Proposed:* a deterministic keyword classifier at ingest writing `derived_severity` and `severity_rationale`, surfaced everywhere as **derived, not source truth**, with low-confidence cases returning undecidable. My proposed classifications are in the golden-set review table and need sign-off.

**A5 — `issue_type` does not exist either.** §12's `issue_spike` and `multi_account_issue` both key on it. Same derivation approach as A4.

**A6 — `tickets.order_id` does not exist.** §6 declares the foreign key; the workbook has no ticket-to-order link of any kind.
Consequence: §12's `repeat_offender_order` rule is **not computable**.
*Recommendation:* drop the rule and name it in the product note rather than inventing a fuzzy join on carrier and timestamp.

**A7 — Only two §12 signals actually fire on this data.**
With the thresholds exactly as written: `sla_breached` fires twice (TKT-501, TKT-505). `issue_spike` needs 3+ in 24h — the maximum is 1. `multi_account_issue` needs 3+ accounts — the maximum is 1. `carrier_degradation` has no baseline (6 orders total). Phase 9's gate requires at least three signals.
*Options:* (a) add rules that honestly fit the data — `security_incident` (P1 credential exposure), `known_issue_match` (open ticket matching KI-208/KI-211), `unattended_p1`; (b) lower thresholds to manufacture volume.
*Recommendation:* **(a)**. Option (b) is precisely the "thresholds too low" failure §18 warns about.

**A8 — There is no first-response timestamp.** SLA targets are *first-response* targets, but no field records when an agent first replied. `assigned_to` is populated without a time.
*Proposed:* for open tickets, `elapsed = snapshot_time - created_at`, treating every open ticket as still awaiting first response.

**A9 — "10% of the shipment fee"** maps to `orders.shipment_fee_inr`. Low risk, stated for completeness.

**A10 — Northstar's INR 5,000 monthly aggregate credit cap is not enforceable.**
No credits ledger exists, so credits already granted this month are unknowable.
*Proposed:* state the cap, never claim remaining headroom, and route any question about remaining balance to escalation.

**A11 — SLA boundary convention.** `elapsed > target` is breached; `elapsed == target` is at-target, not breached. Matters because TKT-501 sits at exactly 30 minutes against policy v3's Enterprise P1 target of 30 minutes. The governing Northstar contract target of 15 minutes makes it breached regardless, but the convention must be explicit.

### 0.2 Assumptions carried from the brainstorm

- Real IDs are `ACCT-001`..`ACCT-004`, not §16's placeholder `ACC-NORTHSTAR` / `ACC-LUMEN`. Nothing is keyed to specific IDs in code.
- Snapshot time is **2026-08-16 11:00 Asia/Kolkata**, read from the README sheet.
- Currency is INR globally; no per-order currency column exists.
- Deprecated documents are visible to internal roles on explicit request, and never to customers.

---

## 1. Model providers

| Job | Provider | Model | Why |
|---|---|---|---|
| Agent loop | Cerebras | config `CHAT_MODEL` | OpenAI-compatible tool calling; speed makes the live tool timeline compelling |
| Embeddings | Gemini | `gemini-embedding-001` @ 1536 dims | Cerebras has no embeddings endpoint; MRL 1536 keeps §6's `VECTOR(1536)` exactly |
| Eval judge, signal naming | Gemini | config `JUDGE_MODEL` | Avoids the answering model grading itself |

**Gate before Phase 5:** a spike runs a 3-hop chain (`lookup_records` → `search_documents` → `evaluate_policy`) ten times and counts runs producing valid tool calls with correct arguments and no invented tool names. Below 9/10 flips `CHAT_PROVIDER=gemini`. The protocol seam makes this a config change.

**Hard client invariant:** `llm/client.py` raises if `tools` and `response_format` are passed in the same request. Validator, judge and signal naming are separate no-tools JSON-schema calls. Enforced by a unit test.

**Embeddings are task-typed:** chunks embed as `RETRIEVAL_DOCUMENT`, queries as `RETRIEVAL_QUERY`. Using one type for both is a silent recall loss.

**Startup assertion:** the app reads the real `doc_chunks.embedding` typmod from `pg_attribute` and fails loudly if it is not `EMBED_DIM`.

---

## 2. Schema deltas from §6

The workbook's real columns differ materially from §6's guesses. Migrations follow the **data**, not the spec.

**`accounts`** — add `status`, `csm`, `premium_support`, `notes`; `contract_file` becomes `contract_doc_id`; no `created_at` in the data.

**`orders`** — replace `pickup_due_at` with `pickup_window_start` and `pickup_window_end`; replace `amount`/`currency` with `shipment_fee_inr`; add `carrier_fault`, `customer_fault`, `cancellation_requested_at`, `notes`; drop `service_level` (absent).

**`tickets`** — no `order_id`, no `severity`, no `issue_type`, no `resolved_at`. Add `subject`, `description`, `channel`, `assigned_to`, `last_customer_message_at`. `historical_resolution` is §6's `resolution_note`, tier 4, context only. Add derived columns `derived_severity`, `derived_issue_type`, `severity_rationale`, all explicitly marked as derived wherever they surface.

**New tables:** `doc_terms` (Section 4) and `session_messages` (backs `GET /chat/{session_id}`, which §6 has no table for).

---

## 3. Retrieval and authority

Hybrid search: `vector_search` and `keyword_search`, both scope-filtered **in SQL** (`WHERE account_scope IS NULL OR account_scope = :scope`), fused by reciprocal rank fusion `sum(1 / (60 + rank))`.

Three additions beyond §9.1:

1. **A reserved-slot pass over the caller's scoped tier-1 documents**, so a contract chunk cannot be crowded out of the candidate pool by generic policy chunks. Bucket promotion is worthless if the chunk never reaches the pool.
2. **A minimum fused-score floor gates promotion**, so an irrelevant contract clause does not top the context merely for being tier 1.
3. **Ranking is a stable sort on `(authority_bucket, fused_score)`** — scoped tier-1 is bucket 0 — making §6.1's override rule a guarantee rather than a heuristic.

Every promotion is written to the trace as an `override_promoted` entry.

**Conflict detection is rules-first**, mirroring §12's "detection is SQL, naming is the LLM". Chunks reduce to claim tuples (subject key from a small lexicon, plus normalised value and unit). Different documents asserting different values for one subject key is a conflict; tier decides the winner; equal tier is unresolved and escalates per §6.1. **Subjects falling outside the lexicon are logged, never dropped silently** — limited subject coverage is a named limitation in the product note, not a surprise in a demo.

---

## 4. Policy terms

`data/terms_overrides.yaml` is the **declared source of truth**. Ingestion verifies that each declared value appears literally in the chunk named by its `source_chunk_id`, and fails at ingest if it does not. Regex extraction is demoted to a **seeder** that proposes rows for curation, never the primary path. `source_chunk_id` is mandatory on every term.

Every term not yet signed off carries `unverified: true`. The eval reports verified and unverified scores as separate figures, so it is visible at a glance which results mean anything.

---

## 5. Testing

Layout follows §3: `unit/` (services + auth, no DB), `integration/` (tools + repositories, test DB), `e2e/` (full chat turns).

**No test calls a real model.** `FakeChatClient` replays scripted tool-call sequences; `FakeEmbedder` returns deterministic hash-derived vectors. Agent-loop tests assert on **tool sequences**, not model prose. A `@pytest.mark.live` subset exercises real providers and is excluded from the default run.

**Hash-derived vectors have no semantic structure.** Ranking and promotion tests therefore build the candidate set directly and call the ranking function with no vector search in the loop. The fake embedder is confined to pipeline and plumbing tests, and its definition carries a comment saying exactly that so the two are never conflated.

**Fixtures are generated, not committed as binaries:** `fpdf2` writes two tiny PDFs (one current, one deprecated, with known conflicting values), `openpyxl` writes a minimal workbook with a README snapshot time. `data/raw/` stays reserved for the real pack.

**Four blocking gates** fail the build:

1. §4.2's layer-import greps.
2. §8.3's cross-account leak tests (documents and records).
3. An e2e test asserting the deprecated fixture policy is never cited in a customer answer.
4. The `tools` + `response_format` guard.

---

## 6. Build sequence

§17's phases with the agreed insertions:

- **Phase 0** — `git init`, skeleton, `.env.example`.
- **Phases 1–4** — unchanged. Phase 1's gate waits on Docker Desktop.
- **Spike between 4 and 5** — Cerebras tool calling, 10 runs, 9/10 gate.
- **Phase 5** — non-streaming `/chat` only. Northstar question correct end to end.
- **Phases 6–7** — confirmation flow, then validator.
- **SSE after Phase 7**, once the loop is proven. The envelope shape does not change, so Phase 5's acceptance test does not move.
- **Phases 8–11** — unchanged.

Docker is the source of truth for running the app: `docker compose up` plus `make setup`. Because `make` is absent on Windows, `setup` is a compose service and the Makefile is a thin alias over `docker compose run --rm setup`. Neither path needs a host Python. `py -3.11` appears only in a README "local dev on Windows" note.

---

## 7. Documentation

Architecture note, product note, and six ADRs: hand-rolled loop over a framework, hybrid retrieval over vector-only, rules-first conflict and signal detection, curated `doc_terms` over model extraction, deterministic tier-bucket promotion, and the Cerebras/Gemini provider split. Plus the §1.8 AI-tool-usage statement.

The architecture note states plainly that **tiktoken is a deterministic ruler, not the serving model's tokenizer**, so chunk sizes are approximate by design.
