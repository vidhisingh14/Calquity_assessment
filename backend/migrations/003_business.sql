-- Columns follow the ACTUAL workbook, not the build spec's section 6, which
-- guessed several that do not exist. Divergences are recorded in the design
-- doc section 2. The important ones:
--   orders  : no pickup_due_at; a pickup WINDOW (start/end). No service_level.
--             shipment_fee_inr replaces amount/currency (currency is global INR).
--             carrier_fault / customer_fault / cancellation_requested_at exist
--             and are load-bearing for the policy engine.
--   tickets : no order_id, no severity, no issue_type, no resolved_at.

CREATE TABLE IF NOT EXISTS accounts (
  account_id       TEXT PRIMARY KEY,
  account_name     TEXT NOT NULL,
  plan             TEXT NOT NULL,          -- Enterprise | Growth | Standard
  status           TEXT NOT NULL,
  csm              TEXT,
  contract_doc_id  TEXT,                   -- FK added in 004, after documents exists
  premium_support  BOOLEAN NOT NULL DEFAULT FALSE,
  notes            TEXT
);

CREATE TABLE IF NOT EXISTS orders (
  order_id                  TEXT PRIMARY KEY,
  account_id                TEXT NOT NULL REFERENCES accounts(account_id),
  carrier                   TEXT,
  status                    TEXT NOT NULL,   -- DRAFT|BOOKED|PICKED_UP|DELIVERED
  booked_at                 TIMESTAMPTZ,
  pickup_window_start       TIMESTAMPTZ,
  pickup_window_end         TIMESTAMPTZ,     -- SOP measures credit delay from HERE
  pickup_actual_at          TIMESTAMPTZ,
  shipment_fee_inr          NUMERIC(12,2),
  carrier_fault             BOOLEAN,
  customer_fault            BOOLEAN,
  cancellation_requested_at TIMESTAMPTZ,     -- assumption A1: fee window ends here
  notes                     TEXT
);
CREATE INDEX IF NOT EXISTS orders_account_idx ON orders (account_id);

CREATE TABLE IF NOT EXISTS tickets (
  ticket_id                TEXT PRIMARY KEY,
  account_id               TEXT NOT NULL REFERENCES accounts(account_id),
  created_at               TIMESTAMPTZ,
  status                   TEXT,
  subject                  TEXT,
  description              TEXT,
  channel                  TEXT,
  assigned_to              TEXT,
  last_customer_message_at TIMESTAMPTZ,

  -- Tier 4. Context only, never authority. Two rows in the supplied data
  -- contain guidance that is provably wrong; the validator must never let a
  -- rule be sourced from this column.
  historical_resolution    TEXT,

  -- DERIVED at ingest, not source truth (assumptions A4/A5). Every surface
  -- that shows these must label them as derived.
  derived_severity         TEXT,            -- P1 | P2 | P3 | NULL when unsure
  severity_rationale       TEXT,
  derived_issue_type       TEXT
);
CREATE INDEX IF NOT EXISTS tickets_account_idx ON tickets (account_id);
CREATE INDEX IF NOT EXISTS tickets_status_idx  ON tickets (status);
