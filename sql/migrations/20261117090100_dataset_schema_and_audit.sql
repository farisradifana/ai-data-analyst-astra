-- 0002 — Schema `dataset` and ETL audit tables.
--
-- `dataset` is NOT added to the Supabase Data API exposed schemas. anon / authenticated get
-- no privileges here; RLS is enabled on every table in migration 0004.

CREATE SCHEMA IF NOT EXISTS dataset AUTHORIZATION postgres;
COMMENT ON SCHEMA dataset IS 'Astra analytics (SYNTHETIC data). Clean, validated tables loaded by the Python ETL.';

REVOKE ALL ON SCHEMA dataset FROM PUBLIC;
REVOKE ALL ON SCHEMA dataset FROM anon, authenticated;

-- One row per pipeline run.
CREATE TABLE IF NOT EXISTS dataset.etl_run (
  run_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  started_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz,
  status        text        NOT NULL DEFAULT 'RUNNING'
                CHECK (status IN ('RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')),
  trigger_type  text        NOT NULL DEFAULT 'MANUAL'
                CHECK (trigger_type IN ('MANUAL', 'SCHEDULED', 'REPROCESS')),
  code_version  text        CHECK (char_length(code_version) <= 64),
  notes         text        CHECK (char_length(notes) <= 2000),
  CHECK (finished_at IS NULL OR finished_at >= started_at)
);
COMMENT ON TABLE dataset.etl_run IS 'One row per ETL run. Status and timing only; no record content.';

-- One row per source file per run (lineage + reconciliation counts).
CREATE TABLE IF NOT EXISTS dataset.etl_run_file (
  run_id            uuid    NOT NULL REFERENCES dataset.etl_run (run_id),
  table_name        text    NOT NULL CHECK (table_name ~ '^[a-z_]{1,40}$'),
  file_name         text    NOT NULL CHECK (char_length(file_name) <= 200),
  file_sha256       char(64) NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
  rows_read         integer NOT NULL CHECK (rows_read >= 0),
  rows_loaded       integer NOT NULL DEFAULT 0 CHECK (rows_loaded >= 0),
  rows_quarantined  integer NOT NULL DEFAULT 0 CHECK (rows_quarantined >= 0),
  rows_duplicate    integer NOT NULL DEFAULT 0 CHECK (rows_duplicate >= 0),
  PRIMARY KEY (run_id, table_name),
  CHECK (rows_loaded + rows_quarantined + rows_duplicate <= rows_read)
);
COMMENT ON TABLE dataset.etl_run_file IS 'Per-file lineage: checksum and row reconciliation (read = loaded + quarantined + duplicate).';

-- Aggregate results of each data-quality check.
CREATE TABLE IF NOT EXISTS dataset.dq_check_result (
  run_id        uuid    NOT NULL REFERENCES dataset.etl_run (run_id),
  table_name    text    NOT NULL CHECK (table_name ~ '^[a-z_]{1,40}$'),
  check_name    text    NOT NULL CHECK (check_name ~ '^[a-z0-9_]{1,64}$'),
  failed_rows   integer NOT NULL CHECK (failed_rows >= 0),
  checked_rows  integer NOT NULL CHECK (checked_rows >= 0),
  severity      text    NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')),
  checked_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, table_name, check_name)
);
COMMENT ON TABLE dataset.dq_check_result IS 'Counts per deterministic DQ check. Safe for dashboards and alerts (no record content).';

-- Records that failed validation (decisions D3/D4, orphan keys, bad dates, ...).
CREATE TABLE IF NOT EXISTS dataset.quarantine_record (
  quarantine_id     bigint  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            uuid    NOT NULL REFERENCES dataset.etl_run (run_id),
  table_name        text    NOT NULL CHECK (table_name ~ '^[a-z_]{1,40}$'),
  source_row_number integer NOT NULL CHECK (source_row_number >= 1),
  record_key        text    CHECK (char_length(record_key) <= 64),
  issue_code        text    NOT NULL CHECK (issue_code ~ '^[A-Z0-9_]{1,64}$'),
  issue_detail      text    CHECK (char_length(issue_detail) <= 500),
  raw_record        jsonb   NOT NULL,  -- may contain PII; never granted to astra_reporting
  status            text    NOT NULL DEFAULT 'OPEN'
                    CHECK (status IN ('OPEN', 'REPROCESSED', 'DISMISSED')),
  -- Laya suggestion (hint only; validation outcome stays with the deterministic rules).
  suggested_category        text CHECK (char_length(suggested_category) <= 64),
  suggested_category_source text CHECK (suggested_category_source IN ('laya', 'rule_fallback')),
  suggested_confidence      numeric(4,3) CHECK (suggested_confidence BETWEEN 0 AND 1),
  created_at        timestamptz NOT NULL DEFAULT now(),
  resolved_at       timestamptz,
  resolved_run_id   uuid    REFERENCES dataset.etl_run (run_id),
  CHECK ((status = 'OPEN') = (resolved_at IS NULL))
);
CREATE INDEX IF NOT EXISTS quarantine_record_open_idx
  ON dataset.quarantine_record (table_name, issue_code) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS quarantine_record_run_idx ON dataset.quarantine_record (run_id);
COMMENT ON TABLE dataset.quarantine_record IS 'Rows that failed validation. raw_record may hold PII and is never readable by astra_reporting.';
COMMENT ON COLUMN dataset.quarantine_record.suggested_category IS 'Laya/fallback DQ category suggestion. Hint only.';
