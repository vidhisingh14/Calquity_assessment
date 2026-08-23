# ParcelPilot AI Support Agent, Build Specification

A complete build spec for a multi tool, multi source AI support agent with strict layer separation.
Written to be handed to a coding agent (Claude Code, Cursor, or a chat session) as the source of truth.

**Version:** 1.0
**Stack:** Python 3.11 + FastAPI + Postgres 16 with pgvector + React (Vite or Next) + TypeScript
**Read this whole file before writing any code.**

---

## 0. How to use this document

If you are an AI coding assistant reading this:

1. Read sections 1 to 5 fully before touching the keyboard. Section 4 is non negotiable, it defines what each file is allowed to do.
2. Build in the phase order given in section 19. Do not jump ahead. Each phase has an acceptance test, a phase is not done until its test passes.
3. Every function you write belongs to exactly one layer. If you cannot name the layer, you have not understood the design yet, ask before writing.
4. Never put business rules in the controller. Never put SQL in the service. Never put HTTP objects in the repository. These three rules prevent most of the bugs this design exists to avoid.
5. When something is ambiguous, choose the option that makes the failure easier to locate, not the option with fewer lines.

If you are a human reading this: section 18 is the debug map, keep it open while testing.

---

## 1. The task in detail

### 1.1 Context

ParcelPilot is a B2B logistics platform. Businesses use it to book and manage shipments across multiple carrier partners. A 20 person customer operations team handles hundreds of support requests per week.

Customers ask about account entitlements, contract specific terms, shipment cancellations, service credits, and support SLAs. They also report product issues that need investigation across order, account, and ticket data.

Today the ops team searches manually across policies, product docs, customer agreements, past tickets, and structured operational data.

### 1.2 What is being built

An AI support system with two user contexts:

- A **customer facing agent** that answers customer questions and escalates when needed.
- **Internal support and ops workflows** that help staff investigate, prioritise, and act on issues.

This spec builds **both**, with a single agent core and role scoped tools, because the tool layer already needs scoping and supporting both costs little extra once that exists.

### 1.3 The source base is deliberately messy

This is the actual difficulty of the task, not a side note.

- Some documents are outdated and superseded by newer versions.
- Customer specific agreements override general policy for that customer only.
- Historical ticket resolutions may contain wrong guidance and are context only, never authority.

The system must handle these deliberately, not treat every source as equally reliable.

### 1.4 Data pack

| File | Nature | Authority |
|---|---|---|
| `01_Support_Policy_v3_CURRENT.pdf` | General policy, current | Tier 2 |
| `02_Support_Policy_v2_DEPRECATED.pdf` | General policy, superseded | Tier 5, excluded by default |
| `03_Cancellation_and_Service_Credit_SOP_v4.pdf` | Operational procedure | Tier 3 |
| `04_Product_Operations_Guide_and_Known_Issues.pdf` | Product reference | Tier 3 |
| `05_Northstar_Logistics_Enterprise_Agreement.pdf` | Customer contract, Northstar only | Tier 1, account scoped |
| `06_LumenWorks_Service_Agreement.pdf` | Customer contract, LumenWorks only | Tier 1, account scoped |
| `ParcelPilot_Assessment_Data.xlsx` | Accounts, orders, tickets, README | Structured truth |

The workbook README sheet states a **dataset snapshot time**. That timestamp, not the wall clock, is the reference time for every time based calculation. This single rule decides whether cancellation window and SLA answers are right or wrong.

### 1.5 Hard requirements

1. **Chatbot with natural language queries.** Uses only the supplied data pack. Accounts for differing authority, freshness, and reliability of sources. Answers confidently when supported, escalates when the request needs human judgement, an unsupported exception, or an action outside system capability.
2. **Access control and data privacy.** Customers see only their own account's data. Internal users are scoped by role. Enforcement lives in the data and tool layer, not in model instructions. Auth may be mocked.
3. **At least three distinct tools.** Document search, structured data lookup or calculation, and a state changing action such as creating an escalation. The action may be mocked locally.
4. **Confirmation before actions.** Any state changing action requires explicit user confirmation before execution.
5. **Multi step requests.** The system must chain tools, for example look up an order, resolve its account, read that account's agreement, check the applicable SOP, run a calculation, then decide whether to escalate.
6. **Interface.** A simple chat UI that ideally shows which tool is running. A hosted link is strongly preferred.
7. **Demo video,** roughly 5 minutes, covering architecture, a working demo, and key decisions with reasons.

### 1.6 Example questions the system must handle

- Can Northstar cancel ORD-1001 without a cancellation fee, and why.
- A pickup is three hours late due to carrier fault, does the customer get a service credit.

These are illustrative. The graders will use other records and questions from the same pack, so nothing may be hard coded to specific IDs. Everything is loaded and reasoned over at runtime.

### 1.7 The two extended problems

**Problem 1, proactive issue detection.** An internal view that surfaces recurring, urgent, or unusual issues across support activity: spikes in similar complaints, clusters on one product issue, high severity tickets near or past SLA, unusual order or ticket patterns, issues hitting several customers at once.

**Problem 2, trust and reliability.** Policies change, contracts override rules, systems disagree, past answers may be wrong. A confidently incorrect answer destroys adoption. The system must make deliberate decisions about source reliability, conflicts, uncertainty, and when a human should step in.

This spec addresses **Problem 2 deeply** (it is woven into retrieval ranking, the answer validator, and the escalation policy) and **Problem 1 as a rules first slice** (section 13).

### 1.8 Deliverables

- Public repository with clear setup and run instructions.
- Hosted application URL.
- Roughly 5 minute demo video.
- Architecture note: agent design, tool design, document and structured data handling, source reliability and conflict handling, major trade offs.
- Product note: which extended problem was chosen and how, what else you would build, what was intentionally left out, one metric for judging usefulness.
- A short statement of which AI coding tools were used and how.

### 1.9 What is actually being evaluated

Read the brief again and the weighting becomes obvious. Feature completion is the floor, not the score. The signal they are looking for:

- Does authority ranking actually work, or does the deprecated policy leak into answers.
- Is access control enforced in code, or merely requested in a prompt.
- Does the system know when it does not know.
- Are the trade offs deliberate and explainable.

Build so that each of these can be demonstrated in under 30 seconds in the video.

---

## 2. Architecture principle

The whole system is a **graph of named steps with typed inputs and outputs**. Think of it exactly like a visual workflow builder: every functional responsibility is one node, each node has one input contract and one output contract, and a bug always belongs to exactly one node.

The code layout mirrors that graph. There is no clever indirection, no shared "utils" dumping ground, and no layer that reaches sideways into another layer's job.

Five stages, five owners:

| Stage | Owner | Runs when |
|---|---|---|
| Ingestion | `ingestion/` | Once, offline, before anything else |
| Request handling | `api/` | Every HTTP request |
| Agent reasoning | `agent/` | Every chat turn |
| Capability execution | `tools/` | When the agent chooses a tool |
| Data access | `repositories/` | Whenever anything touches Postgres |

Plus two cross cutting concerns that get their own homes rather than being sprinkled everywhere: `auth/` and `observability/`.

---

## 3. Repository structure

```
parcelpilot-agent/
├── README.md
├── docs/
│   ├── architecture-note.md
│   ├── product-note.md
│   └── decisions/                  # one file per non obvious decision, ADR style
├── data/
│   ├── raw/                        # the 6 PDFs + the xlsx, untouched
│   └── golden/golden_set.yaml      # eval questions with expected behaviour
│
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app creation, router mounting, nothing else
│   │   ├── config.py               # env parsing, typed settings object, no logic
│   │   │
│   │   ├── api/                    # LAYER 1: controllers, HTTP only
│   │   │   ├── deps.py             # dependency injection, builds AuthContext per request
│   │   │   ├── routes_chat.py
│   │   │   ├── routes_actions.py   # confirm / reject pending actions
│   │   │   ├── routes_signals.py   # proactive detection read API
│   │   │   └── routes_health.py
│   │   │
│   │   ├── schemas/                # LAYER 1.5: pydantic request/response models
│   │   │   ├── chat.py
│   │   │   ├── actions.py
│   │   │   ├── tools.py            # tool arg + tool result models
│   │   │   └── domain.py           # Order, Account, Ticket, DocChunk, Verdict
│   │   │
│   │   ├── auth/                   # LAYER 2: identity and permission, no business rules
│   │   │   ├── context.py          # AuthContext dataclass
│   │   │   ├── resolver.py         # claimed identity -> resolved AuthContext
│   │   │   ├── policies.py         # can_read_account, can_escalate, visible_doc_tiers
│   │   │   └── redaction.py        # field level masking by role
│   │   │
│   │   ├── agent/                  # LAYER 3: orchestration, no SQL, no HTTP
│   │   │   ├── loop.py             # the agent loop, tool call cycle, step budget
│   │   │   ├── prompts.py          # system prompt assembly, versioned strings
│   │   │   ├── registry.py         # tool name -> callable + JSON schema
│   │   │   ├── validator.py        # post answer trust checks
│   │   │   ├── confirmation.py     # two phase action tokens
│   │   │   └── memory.py           # conversation state per session
│   │   │
│   │   ├── tools/                  # LAYER 4: one file per tool, pure capability
│   │   │   ├── base.py             # Tool protocol: name, description, args model, run()
│   │   │   ├── search_documents.py
│   │   │   ├── lookup_records.py
│   │   │   ├── evaluate_policy.py
│   │   │   └── create_escalation.py
│   │   │
│   │   ├── services/               # LAYER 5: business logic, deterministic, testable
│   │   │   ├── retrieval.py        # hybrid search, fusion, authority ranking
│   │   │   ├── conflict.py         # conflict detection between sources
│   │   │   ├── policy_engine.py    # cancellation fee, service credit, SLA math
│   │   │   ├── escalation.py       # escalation construction rules
│   │   │   └── detection.py        # proactive signal rules
│   │   │
│   │   ├── repositories/           # LAYER 6: SQL only, returns domain objects
│   │   │   ├── db.py               # engine, session factory
│   │   │   ├── accounts_repo.py
│   │   │   ├── orders_repo.py
│   │   │   ├── tickets_repo.py
│   │   │   ├── docs_repo.py        # vector + keyword search
│   │   │   ├── escalations_repo.py
│   │   │   ├── signals_repo.py
│   │   │   └── traces_repo.py
│   │   │
│   │   ├── llm/                    # LAYER 7: model access, swappable
│   │   │   ├── client.py           # single chat completion entry point
│   │   │   └── embeddings.py
│   │   │
│   │   └── observability/
│   │       ├── trace.py            # per turn trace object
│   │       └── logging.py          # structured logs, one line per node
│   │
│   ├── ingestion/                  # standalone, run separately from the API
│   │   ├── run_ingest.py           # entry point, orchestrates the steps below
│   │   ├── step_01_load_pdfs.py
│   │   ├── step_02_extract_text.py
│   │   ├── step_03_stamp_authority.py
│   │   ├── step_04_chunk.py
│   │   ├── step_05_embed_and_store.py
│   │   ├── step_06_load_workbook.py
│   │   ├── step_07_normalise.py
│   │   └── step_08_assert.py
│   │
│   ├── jobs/
│   │   └── detect_signals.py       # scheduled proactive detection
│   │
│   ├── eval/
│   │   ├── run_eval.py
│   │   └── judge.py
│   │
│   ├── migrations/                 # plain SQL files, numbered
│   └── tests/
│       ├── unit/                   # services + auth policies, no DB
│       ├── integration/            # tools + repositories, test DB
│       └── e2e/                    # full chat turns
│
└── frontend/
    └── src/
        ├── api/client.ts
        ├── components/
        │   ├── ChatWindow.tsx
        │   ├── ToolTimeline.tsx    # shows which tool is running
        │   ├── SourceCard.tsx      # doc id, tier badge, page
        │   ├── ConfirmationCard.tsx
        │   └── SignalsBoard.tsx
        ├── hooks/useChat.ts
        └── state/session.ts
```

**If you are building this in Node instead of Python,** the layer names stay identical: `routes/` for api, `middleware/auth`, `agent/`, `tools/`, `services/`, `repositories/`, `db/`. Only the syntax changes, none of the rules do.

---

## 4. Layer contracts, the non negotiable rules

Each layer may only call the layer below it. Never sideways, never upward.

```
api  ->  auth, agent
agent  ->  tools, services, llm, observability
tools  ->  services, repositories, auth (read only checks)
services  ->  repositories
repositories  ->  db
```

### 4.1 What each layer may and may not do

**`api/` (controllers)**
- May: parse and validate HTTP input, build the AuthContext through `deps.py`, call one agent or service entry point, shape the HTTP response, map exceptions to status codes.
- May not: contain any `if` statement about business meaning, build SQL, call an LLM, or decide whether something is allowed.
- Rule of thumb: a controller function should be under 20 lines and contain no domain vocabulary beyond passing it through.

**`auth/`**
- May: resolve identity, produce scopes, answer yes or no permission questions, redact fields.
- May not: query business data beyond the user and account lookup it needs, know anything about escalations or policies.
- The AuthContext is created once per request and passed down explicitly. It is never read from a global, and it is never reconstructed inside a tool.

**`agent/`**
- May: assemble prompts, run the tool call loop, enforce step budgets, validate answers, manage pending actions and session memory.
- May not: contain SQL, contain domain formulas, or make HTTP responses.
- The loop knows tool names and schemas. It does not know what a cancellation fee is.

**`tools/`**
- May: validate the model's arguments, apply the auth scope, call services and repositories, shape a compact result.
- May not: call the LLM, call another tool, or trust any account identifier supplied by the model.
- Every tool file exports exactly one tool. One file, one capability.

**`services/`**
- May: contain every business rule and every formula. Pure functions where possible.
- May not: contain SQL, know about the LLM, or know about HTTP.
- This is where a reviewer looks to check your reasoning is correct, so keep it readable and heavily commented on the non obvious rules.

**`repositories/`**
- May: contain SQL, map rows to domain objects, apply scope filters that were passed in.
- May not: contain business rules, format text for the model, or decide permissions on their own.
- Every function that reads account bound data takes an explicit `account_scope` parameter. There is no unscoped variant. If internal staff need cross account reads, that is a separate, explicitly named function such as `list_tickets_all_accounts` which the auth policy gates.

### 4.2 The import direction test

Run this before every commit:

```bash
grep -rn "from app.repositories" backend/app/api/        # must return nothing
grep -rn "from app.api" backend/app/services/            # must return nothing
grep -rn "SELECT\|INSERT\|UPDATE" backend/app/services/  # must return nothing
grep -rn "SELECT\|INSERT\|UPDATE" backend/app/agent/     # must return nothing
```

Any hit is a layer violation, fix it before moving on. Consider adding this as a CI step, it is four lines and it keeps the design honest under deadline pressure.

### 4.3 Error taxonomy

Define these once in `app/errors.py` and use them everywhere. The exception type tells you the layer instantly.

| Exception | Raised by | Maps to HTTP |
|---|---|---|
| `AuthResolutionError` | auth | 401 |
| `PermissionDenied` | auth | 403 |
| `ToolArgumentError` | tools | 422 internally, surfaced to the agent as a retryable tool error |
| `DataNotFound` | repositories | 404 or a tool level empty result |
| `PolicyUndecidable` | services | not an error to the user, triggers escalation |
| `LLMError` | llm | 502 |
| `StepBudgetExceeded` | agent | graceful degraded answer plus escalation offer |

`PolicyUndecidable` is the important one. When the rules cannot reach a confident verdict, the system says so and hands over. It does not guess.

---

## 5. The node to file map

This is the table to use when something breaks. Symptom, then the one file that owns it.

| Node in the flow | Owning file | Input | Output |
|---|---|---|---|
| Load PDFs | `ingestion/step_01_load_pdfs.py` | dir path | list of file handles |
| Extract text | `ingestion/step_02_extract_text.py` | file handle | `{file_name, text, page_count}` |
| Stamp authority | `ingestion/step_03_stamp_authority.py` | extracted doc | doc + metadata block |
| Chunk | `ingestion/step_04_chunk.py` | doc + meta | chunks inheriting meta |
| Embed and store | `ingestion/step_05_embed_and_store.py` | chunks | rows in `doc_chunks` |
| Load workbook | `ingestion/step_06_load_workbook.py` | xlsx path | raw sheet dicts |
| Normalise | `ingestion/step_07_normalise.py` | raw rows | typed rows + snapshot time |
| Assert | `ingestion/step_08_assert.py` | db state | pass or loud failure |
| Receive message | `api/routes_chat.py` | HTTP body | agent call |
| Resolve identity | `auth/resolver.py` | claimed user id | `AuthContext` |
| Assemble prompt | `agent/prompts.py` | AuthContext + snapshot time | system prompt string |
| Agent loop | `agent/loop.py` | message + context | answer + steps |
| Tool: doc search | `tools/search_documents.py` | query + scope | chunks + conflicts |
| Rank by authority | `services/retrieval.py` | candidate chunks | ranked chunks |
| Detect conflicts | `services/conflict.py` | ranked chunks | conflict list |
| Tool: record lookup | `tools/lookup_records.py` | entity + id + scope | rows |
| Tool: policy math | `tools/evaluate_policy.py` | rule + ids | verdict + working |
| The formulas | `services/policy_engine.py` | typed facts | verdict |
| Tool: escalation | `tools/create_escalation.py` | draft | pending action or created id |
| Confirmation tokens | `agent/confirmation.py` | draft | token, then execution |
| Answer validation | `agent/validator.py` | answer + steps | verdict + downgrade |
| Trace write | `observability/trace.py` | turn record | row in `traces` |
| Signal detection | `services/detection.py` | aggregates | signals |

---

## 6. Data model

All migrations live in `backend/migrations/` as numbered plain SQL. No ORM magic, the schema should be readable by anyone reviewing the repo.

```sql
-- 001_extensions.sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 002_system.sql
CREATE TABLE system_meta (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- holds 'snapshot_time' read from the workbook README

-- 003_business.sql
CREATE TABLE accounts (
  account_id      TEXT PRIMARY KEY,
  account_name    TEXT NOT NULL,
  plan_tier       TEXT,
  contract_doc_id TEXT,
  created_at      TIMESTAMPTZ
);

CREATE TABLE orders (
  order_id        TEXT PRIMARY KEY,
  account_id      TEXT NOT NULL REFERENCES accounts(account_id),
  status          TEXT NOT NULL,
  carrier         TEXT,
  service_level   TEXT,
  booked_at       TIMESTAMPTZ,
  pickup_due_at   TIMESTAMPTZ,
  pickup_actual_at TIMESTAMPTZ,
  amount          NUMERIC(12,2),
  currency        TEXT
);

CREATE TABLE tickets (
  ticket_id       TEXT PRIMARY KEY,
  account_id      TEXT NOT NULL REFERENCES accounts(account_id),
  order_id        TEXT REFERENCES orders(order_id),
  severity        TEXT,
  issue_type      TEXT,
  status          TEXT,
  created_at      TIMESTAMPTZ,
  resolved_at     TIMESTAMPTZ,
  resolution_note TEXT      -- context only, never authoritative
);

-- 004_docs.sql
CREATE TABLE documents (
  doc_id          TEXT PRIMARY KEY,
  file_name       TEXT NOT NULL,
  doc_type        TEXT NOT NULL,    -- policy | sop | product_guide | contract
  authority_tier  INT  NOT NULL,    -- 1 highest .. 5 deprecated
  account_scope   TEXT,             -- NULL = applies to everyone
  version_label   TEXT,
  effective_from  DATE,
  superseded_by   TEXT REFERENCES documents(doc_id),
  is_current      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE doc_chunks (
  chunk_id        BIGSERIAL PRIMARY KEY,
  doc_id          TEXT NOT NULL REFERENCES documents(doc_id),
  chunk_index     INT NOT NULL,
  page            INT,
  section_path    TEXT,
  content         TEXT NOT NULL,
  content_tsv     TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
  embedding       VECTOR(1536),
  authority_tier  INT NOT NULL,     -- denormalised on purpose, filters stay cheap
  account_scope   TEXT
);
CREATE INDEX ON doc_chunks USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX ON doc_chunks USING GIN (content_tsv);
CREATE INDEX ON doc_chunks (account_scope, authority_tier);

-- 005_agent.sql
CREATE TABLE escalations (
  escalation_id   TEXT PRIMARY KEY,
  account_id      TEXT NOT NULL,
  created_by      TEXT NOT NULL,
  ticket_id       TEXT,
  order_id        TEXT,
  severity        TEXT NOT NULL,
  summary         TEXT NOT NULL,
  reason          TEXT NOT NULL,
  linked_sources  JSONB,
  status          TEXT NOT NULL DEFAULT 'open',
  idempotency_key TEXT UNIQUE NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE pending_actions (
  token           TEXT PRIMARY KEY,
  session_id      TEXT NOT NULL,
  user_id         TEXT NOT NULL,
  action_type     TEXT NOT NULL,
  payload         JSONB NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed | rejected | expired
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE traces (
  trace_id        BIGSERIAL PRIMARY KEY,
  session_id      TEXT NOT NULL,
  user_id         TEXT NOT NULL,
  role            TEXT NOT NULL,
  question        TEXT NOT NULL,
  answer          TEXT,
  tools_called    JSONB,
  doc_ids_cited   JSONB,
  confidence      TEXT,
  escalated       BOOLEAN,
  validator_flags JSONB,
  latency_ms      INT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE signals (
  signal_id       TEXT PRIMARY KEY,
  signal_type     TEXT NOT NULL,
  severity        TEXT NOT NULL,
  title           TEXT NOT NULL,
  detail          JSONB NOT NULL,
  affected_accounts JSONB,
  first_seen_at   TIMESTAMPTZ NOT NULL,
  last_seen_at    TIMESTAMPTZ NOT NULL,
  status          TEXT NOT NULL DEFAULT 'open'
);

-- 006_users.sql  (mocked auth)
CREATE TABLE users (
  user_id     TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  role        TEXT NOT NULL,        -- customer | support_agent | ops_lead
  account_id  TEXT                  -- NULL for internal staff
);
```

### 6.1 The authority ladder

Define it once, in `documents.authority_tier`, and never re implement it anywhere else.

| Tier | Meaning | Example | Behaviour |
|---|---|---|---|
| 1 | Customer contract, applies to that account only | Northstar Enterprise Agreement | Overrides general policy for that account |
| 2 | Current general policy | Support Policy v3 | Default authority |
| 3 | SOP and product operations guide | Cancellation SOP v4 | Procedural detail, does not override contract |
| 4 | Historical ticket resolutions | `tickets.resolution_note` | Context only, must never be cited as a rule |
| 5 | Deprecated documents | Support Policy v2 | Excluded from retrieval unless explicitly requested, never cited as current |

Two derived rules that live in `services/retrieval.py` and `services/conflict.py`:

- A tier 1 chunk with a matching `account_scope` beats any tier 2 or 3 chunk on the same subject, and the answer must say the contract overrode the general policy.
- If two chunks of the same tier disagree, that is a conflict, not a choice. Surface it and escalate.

---

## 7. Ingestion pipeline

Run with `python -m ingestion.run_ingest`. Idempotent, safe to re run, truncates and reloads.

Each step is a separate module with a single pure function so it can be tested alone.

**Step 1, load PDFs.** Reads `data/raw/*.pdf`. Asserts the expected file count. Fails loudly on a missing file.

**Step 2, extract text.** Per page text extraction with page numbers preserved. **Assert that extracted text length is greater than zero for every page.** A scanned PDF returns a healthy page count and empty text, which then silently poisons every answer. If this fires, add OCR.

**Step 3, stamp authority.** Maps file name to a metadata block. Deterministic, no LLM.

```python
AUTHORITY_MAP = {
  "01_Support_Policy_v3_CURRENT.pdf": dict(
      doc_id="policy_v3", doc_type="policy", authority_tier=2,
      version_label="v3", is_current=True, account_scope=None),
  "02_Support_Policy_v2_DEPRECATED.pdf": dict(
      doc_id="policy_v2", doc_type="policy", authority_tier=5,
      version_label="v2", is_current=False, superseded_by="policy_v3",
      account_scope=None),
  "05_Northstar_Logistics_Enterprise_Agreement.pdf": dict(
      doc_id="contract_northstar", doc_type="contract", authority_tier=1,
      account_scope="<northstar account_id from the workbook>"),
  # ... etc
}
```

An unmatched file name raises. Never default to tier 1 or tier 2.

The account scope for contracts must be resolved against the real `account_id` values in the workbook, not guessed from the file name.

**Step 4, chunk.** Recursive splitting, roughly 800 tokens with 120 overlap, split on section headings where detectable. Every chunk carries the parent metadata plus its page and section path. **The most common bug here is metadata loss on split**, which silently disables all authority filtering downstream. Assert that every produced chunk has a non null `authority_tier`.

**Step 5, embed and store.** Batch embed, insert into `doc_chunks`.

**Step 6, load workbook.** Read every sheet including README. Extract the snapshot time into `system_meta`.

**Step 7, normalise.** Type coercion, and this is where the classic failure lives: **Excel serial dates**. A value like `45678` is a date, not an integer. Convert explicitly, then assert that every parsed timestamp falls within a sane window around the snapshot time. If dates are wrong, every cancellation and SLA answer is wrong while sounding perfectly confident.

Also normalise: status casing, severity vocabulary, currency, null handling, and trimmed IDs.

**Step 8, assert.** Row counts per table, no orphan foreign keys, snapshot time present, every account with a contract has a matching document row, no chunk missing an embedding. Print a summary table. This step is the difference between debugging for ten minutes and debugging for three hours.

---

## 8. Authentication and access control

Mocked authentication is allowed, weak enforcement is not. The distinction that matters: identity may be mocked, authorisation must be real.

### 8.1 AuthContext

```python
@dataclass(frozen=True)
class AuthContext:
    user_id: str
    role: Literal["customer", "support_agent", "ops_lead"]
    account_id: str | None          # None for internal staff
    scopes: frozenset[str]
    def account_scope_filter(self) -> str | None:
        """None means unrestricted, a string means restricted to that account."""
        return self.account_id if self.role == "customer" else None
```

Built once per request in `api/deps.py` by `auth/resolver.py`, which looks the claimed user id up in the `users` table. If the id is unknown, raise `AuthResolutionError`. The context is then passed explicitly down the call chain.

### 8.2 The four enforcement rules

1. **The model never supplies an account identifier that is trusted.** Tool schemas may include an `account_id` argument for internal roles only, and even then the tool re checks it against the auth policy. For customers, the tool overwrites whatever the model sent with the value from AuthContext.
2. **Every account bound repository function takes an explicit scope parameter.** There is no default and no unscoped overload. Cross account reads are separate, explicitly named functions.
3. **Document retrieval is filtered at the SQL level**, `WHERE account_scope IS NULL OR account_scope = :scope`. Never post filter in Python after retrieving everything, and never rely on the prompt to ignore a chunk it can see.
4. **Redaction happens on the way out.** `auth/redaction.py` masks fields a role should not see, such as internal resolution notes or other accounts' contact data.

### 8.3 The test that proves it

Write this test early, it is the one worth demonstrating in the video.

```python
def test_customer_cannot_reach_other_account_contract():
    ctx = AuthContext(user_id="u_lumen", role="customer",
                      account_id="ACC-LUMEN", scopes=...)
    result = search_documents.run(
        args={"query": "Northstar cancellation fee waiver",
              "account_id": "ACC-NORTHSTAR"},   # model tries to override
        ctx=ctx)
    assert all(c.account_scope in (None, "ACC-LUMEN") for c in result.chunks)
    assert "contract_northstar" not in [c.doc_id for c in result.chunks]
```

Add the equivalent for `lookup_records` with an order id belonging to another account. The expected behaviour is an empty result or `DataNotFound`, never a permission hint that leaks the record's existence.

---

## 9. Tool specifications

Every tool implements the same protocol so the registry stays dumb.

```python
class Tool(Protocol):
    name: str
    description: str          # this is what makes the model choose correctly
    args_model: type[BaseModel]
    requires_confirmation: bool
    def run(self, args: BaseModel, ctx: AuthContext) -> ToolResult: ...
```

`ToolResult` is always `{ok: bool, data: dict, meta: {sources: [], notes: []}, error: str | None}`. A failed tool returns a result, it does not raise, so the agent can recover and try something else.

**Tool descriptions are load bearing.** When the agent picks the wrong tool, the fix is in the description string, not the system prompt. Write each description as: what it does, when to use it, when not to use it, one example.

### 9.1 `search_documents`

**Purpose.** Find relevant passages in policies, SOPs, product docs, and the caller's own contract.

```python
class SearchDocumentsArgs(BaseModel):
    query: str
    doc_types: list[Literal["policy","sop","product_guide","contract"]] | None = None
    include_deprecated: bool = False     # internal roles only
    k: int = 8
```

**Flow inside the tool:**
1. Build the scope filter from `ctx`, never from args.
2. `docs_repo.vector_search(...)` and `docs_repo.keyword_search(...)` in parallel, both scope filtered in SQL.
3. `services/retrieval.fuse()` using reciprocal rank fusion, `score = sum(1 / (60 + rank))`.
4. `services/retrieval.apply_authority()`: drop tier 5 unless `include_deprecated` and the role permits, then boost tier 1 chunks whose `account_scope` matches the caller.
5. `services/conflict.detect()` compares the top chunks for contradictory claims on the same subject.

**Output:**
```json
{
  "chunks": [
    {"doc_id": "contract_northstar", "tier": 1, "page": 4,
     "section": "5.2 Cancellation", "text": "...", "score": 0.81}
  ],
  "conflicts": [
    {"subject": "cancellation fee window",
     "winning_doc": "contract_northstar", "losing_doc": "policy_v3",
     "reason": "account specific contract overrides general policy"}
  ],
  "excluded": [{"doc_id": "policy_v2", "reason": "deprecated, superseded by policy_v3"}]
}
```

The `excluded` array is not decoration. Showing what was deliberately ignored is a large part of the trust story, and it renders nicely in the UI.

### 9.2 `lookup_records`

**Purpose.** Read structured account, order, and ticket data.

```python
class LookupRecordsArgs(BaseModel):
    entity: Literal["account","order","ticket"]
    record_id: str | None = None
    filters: dict | None = None      # whitelisted keys only
    limit: int = 20
```

**Rules.**
- The model never writes SQL. The tool switches on `entity` and calls a fixed repository function with bound parameters.
- `filters` keys are validated against a per entity allow list. An unknown key returns a tool error listing the valid keys, which the model can then correct.
- The scope filter is appended by the tool, always.
- Results are truncated at `limit` with `truncated: true` so the model knows not to reason as if it saw everything.
- `tickets.resolution_note` is returned with an explicit marker: `"authority": "context_only"`. The agent prompt states that context only fields may inform investigation but may never be cited as a rule.

### 9.3 `evaluate_policy`

**Purpose.** All arithmetic and all rule evaluation. The model supplies identifiers, the code produces the verdict.

```python
class EvaluatePolicyArgs(BaseModel):
    rule: Literal["cancellation_fee","service_credit","sla_status"]
    order_id: str | None = None
    ticket_id: str | None = None
    stated_facts: dict | None = None   # e.g. {"delay_hours": 3, "fault": "carrier"}
```

**Flow:** fetch the record, fetch the governing document terms, then run a pure function in `services/policy_engine.py`.

```python
def evaluate_cancellation(order, contract_terms, general_terms, snapshot_time):
    terms = contract_terms or general_terms
    hours_to_pickup = (order.pickup_due_at - snapshot_time).total_seconds() / 3600
    ...
    return Verdict(
        outcome="fee_waived" | "fee_applies" | "undecidable",
        governing_source=terms.doc_id,
        override_applied=contract_terms is not None,
        working=[
            f"snapshot_time = {snapshot_time.isoformat()}",
            f"pickup_due_at = {order.pickup_due_at.isoformat()}",
            f"hours_to_pickup = {hours_to_pickup:.2f}",
            f"free_cancellation_window = {terms.window_hours}h",
        ],
        confidence="high",
    )
```

**Three rules that matter here:**
- Time is measured from `system_meta.snapshot_time`, never `datetime.now()`. Read it once at startup, pass it in.
- `working` is a human readable list of steps. It goes into the UI. A support agent who can see the arithmetic will trust the system, one who cannot will not.
- If a required term is missing or the facts are ambiguous, return `outcome="undecidable"` with a reason. That flows straight into an escalation. Never guess a number to fill a gap.

### 9.4 `create_escalation`

**Purpose.** The state changing action. Requires confirmation.

```python
class CreateEscalationArgs(BaseModel):
    summary: str
    reason: str
    severity: Literal["low","medium","high","urgent"]
    order_id: str | None = None
    ticket_id: str | None = None
    linked_sources: list[str] = []
```

**Two phase behaviour.**

*Phase 1, prepare.* The tool validates the payload, resolves the account from `ctx`, builds the full escalation object, stores it in `pending_actions` with a random token and a 15 minute expiry, and returns the draft plus the token. **Nothing is written to `escalations`.**

*Phase 2, execute.* The user confirms through `POST /actions/{token}/confirm`. The controller passes the token to `agent/confirmation.py`, which checks that the token exists, is still pending, has not expired, and belongs to the same `session_id` and `user_id`. Only then does `escalations_repo.create()` run, using `idempotency_key` derived from the token so a duplicate confirm cannot create a second row.

Rejection marks the row `rejected` and returns to the chat with the reason.

This is the requirement graders test directly, so make the state machine explicit and make the UI show it.

---

## 10. The agent loop

`agent/loop.py`. Hand rolled on purpose, so every step is inspectable and streamable.

```
1. Load session memory for session_id.
2. Build messages: system prompt + history + new user message.
3. Loop, max 8 steps:
   a. Call the LLM with the tool schemas from the registry.
   b. If the response has no tool call, break with the draft answer.
   c. For each tool call:
      - Look up the tool in the registry. Unknown name -> tool error back to the model.
      - Validate args against the tool's pydantic model. Invalid -> tool error with the schema.
      - If tool.requires_confirmation and there is no valid confirmation token:
          run in prepare mode, append the draft to the turn, and break the loop.
      - Otherwise run the tool with ctx, append the ToolResult to messages.
      - Record the step in the trace.
   d. Continue.
4. Run the validator on the draft answer.
5. Persist memory, write the trace, return the response envelope.
```

**Step budget.** Eight steps is enough for the deepest legitimate chain in this dataset (order, account, contract, policy, calculation, decide). Hitting the budget is a signal, not a crash: return what is known, state that the chain was cut short, and offer escalation.

**Response envelope,** the single shape the frontend consumes:

```json
{
  "session_id": "...",
  "answer": "...",
  "confidence": "high | medium | low",
  "sources": [{"doc_id": "policy_v3", "tier": 2, "page": 7, "label": "Support Policy v3"}],
  "steps": [{"tool": "lookup_records", "args_summary": "order ORD-1001", "ok": true, "ms": 42}],
  "conflicts": [...],
  "excluded_sources": [...],
  "pending_action": {"token": "...", "type": "create_escalation", "preview": {...}} ,
  "escalation_offered": false
}
```

### 10.1 System prompt structure

Keep it in `agent/prompts.py` as a versioned constant, so the eval harness can attribute score changes to prompt versions.

Sections, in this order:
1. Role and scope. What ParcelPilot is, who the caller is (role, account name, never the raw account id), what the assistant may do.
2. The authority ladder, stated plainly, including that ticket resolutions are context only and deprecated documents are not current guidance.
3. The reference time. State the snapshot time explicitly and instruct that all time reasoning uses it.
4. Tool usage guidance. Prefer `evaluate_policy` over doing arithmetic. Never state a policy rule without retrieving it first.
5. Escalation policy, as an explicit list (see 11.2).
6. Answer format. Cite `doc_id` for every rule based claim. Say when a contract overrode general policy. State uncertainty rather than hedging vaguely.

The prompt is a guide to behaviour. It is never the enforcement mechanism for access control, and it is never where the maths happens.

---

## 11. The trust layer

This is the answer to Problem 2, and it is deliberately code rather than prompting.

### 11.1 The validator

`agent/validator.py` runs after the model produces a draft answer and before the user sees it.

Checks, each returning a flag:

| Check | Fails when | Consequence |
|---|---|---|
| Citation existence | A cited `doc_id` never appeared in any tool result this turn | Strip the claim, downgrade confidence to low |
| Deprecated citation | Any cited chunk has `authority_tier` 5 | Block the answer, escalate |
| Context only citation | The answer states a rule sourced from a ticket resolution | Rewrite as investigation context, escalate if the rule mattered |
| Ungrounded numbers | A number appears in the answer that no tool returned | Downgrade, ask `evaluate_policy` to be run |
| Unresolved conflict | `conflicts` is non empty and the answer does not mention it | Append the conflict, downgrade to medium |
| Scope leak | Any `account_scope` in the sources does not match the caller | Hard block, log an incident, return a generic error |
| Undecidable verdict | `evaluate_policy` returned undecidable but the answer is confident | Replace with an escalation offer |

Confidence is derived from these flags plus the top source tier, never asked of the model. A self reported confidence score is close to meaningless, a derived one is auditable.

### 11.2 When to escalate

Escalation is offered, not forced, and the trigger list is explicit:

- No supporting source was found above tier 3.
- A verdict is `undecidable`.
- Two sources of equal authority conflict.
- The request asks for an exception to a written rule, for example a goodwill waiver.
- The request needs an action the system cannot perform.
- The caller explicitly asks for a human.
- The step budget was exhausted mid chain.

Each of these maps to a constant in `services/escalation.py` so the reason string in the escalation record is machine readable, and later analysable.

---

## 12. Proactive detection, Problem 1

`jobs/detect_signals.py`, run on a schedule (cron, APScheduler, or a Render cron job). Kept deliberately thin, and honest about being thin.

**Detection is SQL. Naming is the LLM.** If the detection itself is model driven, results change run to run and the ops team stops trusting the board within a week.

Rules to implement in `services/detection.py`, each a pure function over aggregate rows:

| Signal | Rule | Severity |
|---|---|---|
| `issue_spike` | Ticket count for one `issue_type` in the last 24h exceeds 2x the 7 day daily mean and count is at least 3 | high |
| `sla_risk` | High or urgent tickets, open, within 2h of the SLA deadline computed from the policy | urgent |
| `sla_breached` | Same, already past deadline | urgent |
| `multi_account_issue` | One `issue_type` with open tickets across 3 or more accounts | high |
| `repeat_offender_order` | One order with 3 or more tickets | medium |
| `carrier_degradation` | One carrier's late pickup rate in the window exceeds 2x its baseline | medium |

Each rule produces a `Signal` with a deterministic `signal_id` (hash of type plus the entities involved) so re runs upsert instead of duplicating. Only after that does a single LLM call write a one line human title and a suggested next action per signal.

The internal UI reads `GET /signals` and shows an ops board grouped by severity. Clicking a signal opens the chat prefilled with an investigation question, which connects Problem 1 back to the agent instead of leaving it a dead dashboard.

---

## 13. API surface

Keep it small. Every route is thin.

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/chat` | `{session_id, message}` | response envelope (section 10) |
| `GET` | `/chat/{session_id}` | | message history |
| `POST` | `/actions/{token}/confirm` | | `{escalation_id, status}` |
| `POST` | `/actions/{token}/reject` | `{reason?}` | `{status}` |
| `GET` | `/signals` | `?severity=&status=` | signal list, internal roles only |
| `GET` | `/documents/{doc_id}/chunk/{n}` | | chunk text for the source drawer |
| `GET` | `/healthz` | | `{status, snapshot_time, doc_count, row_counts}` |

Identity for the mock: an `X-User-Id` header, plus a user switcher in the UI. The health endpoint doubles as an ingestion sanity check, which is genuinely useful when the hosted deploy behaves differently from local.

Streaming is optional. If time allows, make `/chat` a server sent event stream emitting `step` events as tools run and a final `answer` event. The tool timeline updating live is the single most convincing thing in a demo video.

---

## 14. Frontend

Small and purposeful. Three screens at most.

**Chat.** Message list, composer, and a user switcher in the header showing the active role and account. The switcher matters, it lets you demonstrate access control in one click during the video.

**Tool timeline.** A vertical strip under each assistant message showing each step: tool name, a one line argument summary, duration, and success. Collapsed by default, expandable to raw arguments and results.

**Source cards.** Under the answer, one card per cited document with a tier badge, page number, and a click to open the chunk text. Excluded sources appear as a muted line, for example "Support Policy v2 was excluded, superseded by v3".

**Confirmation card.** When `pending_action` is present, render the draft escalation as a card with the fields laid out, plus Confirm and Reject buttons. The composer is disabled until the user resolves it, so the confirmation gate is visible rather than implied.

**Signals board.** Internal roles only. Severity grouped list, each item opening an investigation in chat.

---

## 15. Observability

One trace row per turn, written by `observability/trace.py`. Never optional, never sampled at this scale.

Log one structured line per node with `session_id`, node name, duration, and outcome. When a bug report says "it answered wrong at 4pm", the trace plus the node lines should locate the failure without reproducing it.

**The one metric for the product note:** *deflection with correctness*, meaning the percentage of turns that were answered without escalation **and** passed all validator checks **and** were not later contradicted by a human. Raw deflection alone rewards confident wrong answers, which is precisely the failure mode the client is worried about.

Secondary metrics worth logging from day one: escalation rate by reason, tool error rate, p95 latency, and the share of answers citing a tier 1 contract when one existed.

---

## 16. Evaluation harness

`eval/run_eval.py`, driven by `data/golden/golden_set.yaml`. Aim for 30 questions. This is what separates a demo from a system.

```yaml
- id: q_northstar_cancel_fee
  role: customer
  account: ACC-NORTHSTAR
  question: "Can I cancel ORD-1001 without a cancellation fee?"
  expect:
    verdict_contains: ["fee", "waived"]
    must_cite: ["contract_northstar"]
    must_not_cite: ["policy_v2"]
    override_applied: true
    escalated: false

- id: q_cross_account_leak
  role: customer
  account: ACC-LUMEN
  question: "What are Northstar's cancellation terms?"
  expect:
    must_not_cite: ["contract_northstar"]
    answer_must_not_contain: ["Northstar"]
    escalated: false

- id: q_deprecated_trap
  role: customer
  account: ACC-LUMEN
  question: "What was the old 48 hour support policy?"
  expect:
    must_not_cite: ["policy_v2"]
    confidence: "low"
```

Categories to cover:
- Straightforward policy questions, answerable from tier 2.
- Contract override cases, where tier 1 must win and the answer must say so.
- Deprecated document traps.
- Cross account access attempts, including the model being told an account id in the message.
- Multi hop chains requiring three or more tools.
- Calculation cases with a known correct number.
- Undecidable cases that must escalate.
- Ticket resolution traps, where a past resolution gives wrong guidance.

Scoring is programmatic where possible (citations, escalation flag, override flag) and LLM judged only for answer correctness. Run before and after every change, and record the score with the prompt version in the results file.

---

## 17. Build order

Do not reorder these. Each phase ends with a check you can actually run.

**Phase 1, foundations.** Repo skeleton with all layer folders, config, Postgres with pgvector running in Docker, migrations applied, `/healthz` returning row counts.
*Done when:* `curl /healthz` returns zeros without error.

**Phase 2, ingestion.** All eight steps, including every assertion.
*Done when:* `/healthz` shows the correct document count, chunk count, account, order, and ticket counts, and the snapshot time. Manually spot check three chunks for correct tier and scope.

**Phase 3, data layer and auth.** Repositories with scoped functions, AuthContext, resolver, policies, and the cross account tests from section 8.3.
*Done when:* the leak tests pass, and they must pass before any LLM code is written.

**Phase 4, tools without an agent.** All four tools callable from a script with a hand built AuthContext.
*Done when:* you can answer the Northstar ORD-1001 question by calling tools manually in the right order and getting the correct verdict.

**Phase 5, the agent loop.** Registry, prompt, loop, memory, tracing.
*Done when:* the same question is answered end to end through `/chat` with the right tool sequence in the trace.

**Phase 6, confirmation flow.** Pending actions, tokens, confirm and reject routes, idempotency.
*Done when:* a double confirm creates exactly one escalation, and an expired token is refused.

**Phase 7, the validator.** All checks from 11.1 plus derived confidence.
*Done when:* a prompt injected question asking for another account's contract returns a hard block and logs an incident.

**Phase 8, frontend.** Chat, timeline, source cards, confirmation card, user switcher.
*Done when:* the access control demo takes one click.

**Phase 9, proactive detection.** Rules, job, signals API, board.
*Done when:* the board shows at least three real signals from the supplied data.

**Phase 10, eval and hardening.** Golden set, judge, run, fix the worst failures, write the notes.
*Done when:* the eval score is recorded in the repo and the architecture and product notes are written.

**Phase 11, deploy and record.** Host it, then record the video.

If time runs short, cut phase 9 before phase 7. A trustworthy narrow system beats a broad unreliable one, and the brief says so almost explicitly.

---

## 18. Debug map

The point of the whole structure. Symptom, then the one file that owns it.

| Symptom | Owner | Usual cause |
|---|---|---|
| Answer cites the deprecated policy | `ingestion/step_03` then `services/retrieval.py` | Wrong tier stamped, or the tier filter is not in the SQL |
| Contract does not override general policy | `services/policy_engine.py` | Contract terms never fetched, or override branch not taken |
| Right document, wrong number | `services/policy_engine.py` | Arithmetic done by the model instead of the tool |
| Everything is off by years | `ingestion/step_07_normalise.py` | Excel serial dates not converted |
| Time based answers subtly wrong | `agent/prompts.py` and `policy_engine` | `datetime.now()` used instead of snapshot time |
| Customer sees another account's data | `auth/resolver.py` or the scope filter in the repo | Account id trusted from model args |
| Agent picks the wrong tool | `tools/*.py` description strings | Description says what it does but not when to use it |
| Agent loops on the same tool | `agent/loop.py` | Tool errors not surfaced clearly, no step budget |
| Sources look invented | `agent/validator.py` | Citation existence check missing or too lenient |
| Escalation created without asking | `agent/confirmation.py` | Tool ran in execute mode without a token check |
| Duplicate escalations | `escalations_repo.py` | Missing idempotency key |
| Forgets a pending action next turn | `agent/memory.py` | Session state not persisted, or wrong session key |
| Retrieval slow | `repositories/docs_repo.py` | Missing ivfflat or GIN index, or k too large |
| Signals board noisy or duplicating | `services/detection.py` | Non deterministic signal id, or thresholds too low |
| Works locally, wrong in production | `/healthz` | Ingestion never ran on the deployed database |

---

## 19. Configuration and deployment

`config.py` parses these once into a typed settings object. No `os.getenv` anywhere else.

```
DATABASE_URL=
LLM_PROVIDER=anthropic|openai
LLM_API_KEY=
LLM_MODEL=
EMBEDDING_MODEL=
MAX_AGENT_STEPS=8
PENDING_ACTION_TTL_MINUTES=15
RETRIEVAL_K=8
ENABLE_DEPRECATED_DOCS_FOR_INTERNAL=true
LOG_LEVEL=info
```

Deployment: backend on Render or Railway (both give a managed Postgres, and pgvector is available), frontend on Vercel. Run ingestion as a one off job against the production database after the first deploy, then confirm through `/healthz`. Seed at least three demo users, one per role, so a reviewer can switch context without any setup.

Add a `docker-compose.yml` with Postgres plus pgvector and a `make setup` target that migrates and ingests in one command. Reviewers who cannot run your project in five minutes will judge it on the video alone.

---

## 20. Documentation to write alongside the code

**`docs/architecture-note.md`,** one page: the layer diagram, the agent loop, the tool table with input and output contracts, the authority ladder, how conflicts are resolved, and three trade offs with reasoning. Name the trade offs plainly, for example a hand rolled loop instead of a framework, hybrid retrieval instead of vector only, and rules based detection instead of model based clustering.

**`docs/product-note.md`,** one page: which extended problem was chosen and why, what would be built next in priority order, what was intentionally left out and why that was the right call under the time budget, and the single usefulness metric from section 15.

**`docs/decisions/`,** short files for anything a reviewer might question. Four to six of these signals engineering maturity more than a longer README does.

---

## 21. Reusing this spec for a different agent project

The specific business logic changes, the skeleton does not. To adapt this to another multi source agent build, change these seven things and leave everything else alone.

1. **The corpus and its authority ladder.** Every domain has one: in legal it is statute over commentary, in medicine it is guideline over case report, in finance it is filing over analyst note. Write the ladder before writing any retrieval code.
2. **The structured entities.** Swap accounts, orders, and tickets for the domain's nouns. Keep one repository per entity and keep every scoped function explicit.
3. **The scope dimension.** Here it is `account_id`. Elsewhere it might be `tenant_id`, `patient_id`, or `matter_id`. Whatever it is, it lives in AuthContext and is applied in SQL, never in a prompt.
4. **The deterministic engine.** Every serious agent has one place where the maths must be exactly right. Name it, keep it pure, and forbid the model from doing that work.
5. **The state changing actions.** List them, decide which need confirmation (assume all of them do), and reuse the pending action token flow unchanged.
6. **The validator checks.** The seven checks in 11.1 generalise directly. Citation existence, stale source, ungrounded numbers, unresolved conflict, and scope leak apply to almost any retrieval agent.
7. **The golden set.** Rewrite the questions, keep the categories: happy path, override case, stale source trap, cross scope attempt, multi hop, calculation, and undecidable.

Everything else, the folder layout, the layer rules, the tool protocol, the response envelope, the trace table, the debug map, transfers as is.

---

## 22. Quick checklist before submitting

- [ ] Ingestion asserts pass and `/healthz` matches expectations on the hosted deployment
- [ ] Cross account leak tests pass for both documents and records
- [ ] Deprecated policy never appears in a customer answer
- [ ] A contract override is stated explicitly in the answer text when it happens
- [ ] Every number in an answer traces to a tool result
- [ ] Double confirm creates exactly one escalation
- [ ] Expired token is refused with a clear message
- [ ] Tool timeline visible in the UI
- [ ] Excluded sources visible in the UI
- [ ] Role switcher demonstrates access control in one click
- [ ] Eval results committed with the prompt version
- [ ] README runs from clone to working app in under five minutes
- [ ] Architecture note, product note, and AI tool usage statement written
- [ ] Demo video covers architecture, live demo, and three decisions with reasons
