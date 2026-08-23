CREATE TABLE IF NOT EXISTS documents (
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

ALTER TABLE accounts
  DROP CONSTRAINT IF EXISTS accounts_contract_doc_fk;
ALTER TABLE accounts
  ADD CONSTRAINT accounts_contract_doc_fk
  FOREIGN KEY (contract_doc_id) REFERENCES documents(doc_id);

CREATE TABLE IF NOT EXISTS doc_chunks (
  chunk_id        BIGSERIAL PRIMARY KEY,
  doc_id          TEXT NOT NULL REFERENCES documents(doc_id),
  chunk_index     INT NOT NULL,
  page            INT,
  section_path    TEXT,
  content         TEXT NOT NULL,
  content_tsv     TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
  embedding       VECTOR(1536),
  -- Denormalised on purpose so scope/tier filters stay cheap and stay in SQL.
  authority_tier  INT NOT NULL,
  account_scope   TEXT
);
CREATE INDEX IF NOT EXISTS doc_chunks_embedding_idx
  ON doc_chunks USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS doc_chunks_tsv_idx
  ON doc_chunks USING GIN (content_tsv);
CREATE INDEX IF NOT EXISTS doc_chunks_scope_tier_idx
  ON doc_chunks (account_scope, authority_tier);

-- Declared policy terms. data/terms_overrides.yaml is the SOURCE OF TRUTH;
-- ingestion verifies each declared value appears literally in the chunk named
-- by source_chunk_id and fails the ingest otherwise. Regex extraction only
-- proposes rows for curation.
CREATE TABLE IF NOT EXISTS doc_terms (
  term_id         BIGSERIAL PRIMARY KEY,
  doc_id          TEXT NOT NULL REFERENCES documents(doc_id),
  term_key        TEXT NOT NULL,
  term_value      JSONB NOT NULL,
  unit            TEXT,
  source_chunk_id BIGINT NOT NULL REFERENCES doc_chunks(chunk_id),

  -- Denormalised from documents so the tier-5 exclusion can be expressed in
  -- the term lookup SQL itself rather than relying on a join every caller
  -- must remember to write. See design doc 4.2.
  authority_tier  INT NOT NULL,
  account_scope   TEXT,
  deprecated      BOOLEAN NOT NULL DEFAULT FALSE,

  -- False for terms that are stated but not computable from available data,
  -- e.g. Northstar's monthly aggregate credit cap (assumption A10).
  enforceable     BOOLEAN NOT NULL DEFAULT TRUE,

  -- True until a human signs the row off in terms_overrides.yaml.
  unverified      BOOLEAN NOT NULL DEFAULT TRUE,

  UNIQUE (doc_id, term_key)
);
CREATE INDEX IF NOT EXISTS doc_terms_lookup_idx
  ON doc_terms (term_key, authority_tier);
