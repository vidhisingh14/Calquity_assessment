-- Holds 'snapshot_time' read from the workbook README sheet, plus any
-- ingestion facts /healthz needs to surface (e.g. skipped empty pages).
CREATE TABLE IF NOT EXISTS system_meta (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
