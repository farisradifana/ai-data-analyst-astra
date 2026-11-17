-- 0007 — Corrections: fix quarantined data in the database instead of the source CSV.
--
-- One row = one corrected cell: (table_name, record_key[, source_row_number], column_name) -> value.
-- Every ETL run reads the active corrections, overlays them on the raw row (source files stay
-- unchanged, for audit), then validates as usual. A corrected row that passes is loaded and its
-- OPEN quarantine record becomes GRADUATED; one that still fails stays OPEN (new rule if any).
-- Corrections persist across runs. Nothing is deleted: set is_active = false to withdraw one.
--   record_key         the row's primary key as in the source file (case-insensitive)
--   source_row_number  optional; limits the fix to one source line when the key is shared
--                      (DUPLICATE_PRIMARY_KEY). Line numbers shift if the file changes.
--   column_name        source CSV column (see raw-data headers / src/astra_etl/spec.py)
--   corrected_value    NULL = make the cell blank
-- The ETL writes last_outcome: LOADED | STILL_QUARANTINED | KEY_NOT_FOUND | COLUMN_UNKNOWN.

CREATE TABLE IF NOT EXISTS dataset.quarantine_correction (
  correction_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  table_name          text NOT NULL CHECK (table_name IN (
                        'customers', 'employees', 'suppliers', 'products', 'sales_transactions',
                        'service_orders', 'procurement', 'inventory', 'expenses', 'attendance')),
  record_key          text NOT NULL CHECK (record_key ~ '^[A-Za-z0-9-]{1,64}$'),
  source_row_number   integer CHECK (source_row_number >= 2),
  column_name         text NOT NULL CHECK (column_name ~ '^[a-z_]{1,64}$'),
  corrected_value     text CHECK (char_length(corrected_value) <= 500),
  reason              text NOT NULL CHECK (char_length(reason) BETWEEN 3 AND 300),
  corrected_by        text NOT NULL DEFAULT current_user CHECK (char_length(corrected_by) <= 64),
  is_active           boolean NOT NULL DEFAULT true,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  last_applied_run_id uuid REFERENCES dataset.etl_run (run_id),
  last_applied_at     timestamptz,
  last_outcome        text CHECK (last_outcome IN ('LOADED', 'STILL_QUARANTINED', 'KEY_NOT_FOUND', 'COLUMN_UNKNOWN'))
);
COMMENT ON TABLE dataset.quarantine_correction IS
  'Analyst fixes for quarantined rows, applied on top of the raw source by every ETL run. May hold PII.';

-- One active fix per cell.
CREATE UNIQUE INDEX IF NOT EXISTS quarantine_correction_active_cell_uq
  ON dataset.quarantine_correction (table_name, upper(record_key), coalesce(source_row_number, 0), column_name)
  WHERE is_active;

-- Which source columns were corrected on each quarantine record (names only).
ALTER TABLE dataset.quarantine_record
  ADD COLUMN IF NOT EXISTS corrected_columns text[] NOT NULL DEFAULT '{}';
COMMENT ON COLUMN dataset.quarantine_record.corrected_columns IS
  'Source columns overridden by dataset.quarantine_correction when this record was produced.';

-- Access: same model as 0004. Analyst may insert/update (deactivate), never delete.
ALTER TABLE dataset.quarantine_correction ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON dataset.quarantine_correction FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON dataset.quarantine_correction TO astra_analyst;
DROP POLICY IF EXISTS analyst_select ON dataset.quarantine_correction;
DROP POLICY IF EXISTS analyst_insert ON dataset.quarantine_correction;
DROP POLICY IF EXISTS analyst_update ON dataset.quarantine_correction;
DROP POLICY IF EXISTS reporting_select ON dataset.quarantine_correction;
CREATE POLICY analyst_select ON dataset.quarantine_correction FOR SELECT TO astra_analyst USING (true);
CREATE POLICY analyst_insert ON dataset.quarantine_correction FOR INSERT TO astra_analyst WITH CHECK (true);
CREATE POLICY analyst_update ON dataset.quarantine_correction FOR UPDATE TO astra_analyst USING (true) WITH CHECK (true);
CREATE POLICY reporting_select ON dataset.quarantine_correction FOR SELECT TO astra_reporting USING (true);

-- Reporting sees only metadata: no key, value, reason or author.
GRANT SELECT (correction_id, table_name, column_name, is_active, created_at, updated_at,
              last_applied_run_id, last_applied_at, last_outcome)
  ON dataset.quarantine_correction TO astra_reporting;
GRANT SELECT (corrected_columns) ON dataset.quarantine_record TO astra_reporting;

-- Correction progress per table and outcome.
CREATE OR REPLACE VIEW dataset.v_correction_status WITH (security_invoker = true) AS
SELECT table_name, column_name, is_active, coalesce(last_outcome, 'NOT_YET_APPLIED') AS last_outcome,
       count(*) AS corrections, max(updated_at) AS last_change_at
FROM dataset.quarantine_correction
GROUP BY 1, 2, 3, 4;
REVOKE ALL ON dataset.v_correction_status FROM PUBLIC, anon, authenticated;
GRANT SELECT ON dataset.v_correction_status TO astra_analyst, astra_reporting;
