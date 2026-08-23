CREATE TABLE IF NOT EXISTS escalations (
  escalation_id   TEXT PRIMARY KEY,
  account_id      TEXT NOT NULL,
  created_by      TEXT NOT NULL,
  ticket_id       TEXT,
  order_id        TEXT,
  severity        TEXT NOT NULL,
  summary         TEXT NOT NULL,
  reason          TEXT NOT NULL,       -- machine-readable constant from services/escalation.py
  linked_sources  JSONB,
  status          TEXT NOT NULL DEFAULT 'open',
  -- Derived from the confirmation token, so a double confirm cannot create a
  -- second row. This is the constraint, not the application logic.
  idempotency_key TEXT UNIQUE NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pending_actions (
  token           TEXT PRIMARY KEY,
  session_id      TEXT NOT NULL,
  user_id         TEXT NOT NULL,
  action_type     TEXT NOT NULL,
  payload         JSONB NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending',  -- pending|confirmed|rejected|expired
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at      TIMESTAMPTZ NOT NULL
);

-- Backs GET /chat/{session_id}. Section 6 of the build spec defines traces but
-- no message history, so the documented API had no table behind it.
CREATE TABLE IF NOT EXISTS session_messages (
  message_id  BIGSERIAL PRIMARY KEY,
  session_id  TEXT NOT NULL,
  user_id     TEXT NOT NULL,
  role        TEXT NOT NULL,        -- user | assistant
  content     TEXT NOT NULL,
  envelope    JSONB,                -- full response envelope for assistant turns
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS session_messages_session_idx
  ON session_messages (session_id, message_id);

CREATE TABLE IF NOT EXISTS traces (
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
  validator_flags JSONB,            -- scope-leak incidents land here
  overrides       JSONB,            -- every authority promotion, per design doc 3
  latency_ms      INT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signals (
  signal_id         TEXT PRIMARY KEY,   -- deterministic hash: re-runs upsert
  signal_type       TEXT NOT NULL,
  severity          TEXT NOT NULL,
  title             TEXT NOT NULL,
  detail            JSONB NOT NULL,
  affected_accounts JSONB,
  first_seen_at     TIMESTAMPTZ NOT NULL,
  last_seen_at      TIMESTAMPTZ NOT NULL,
  status            TEXT NOT NULL DEFAULT 'open'
);
