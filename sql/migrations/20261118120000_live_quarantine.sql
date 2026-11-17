-- 0008 — Read each source file once; fix and graduate rows inside the quarantine table.
--
-- New model (replaces the per-run copies of 0006 and the correction overlay of 0007):
--   * dataset.source_file registers every file the ETL has read (table, name, sha256).
--     A registered file is never read again; a registered name with a different checksum is an
--     error (new data must arrive as a new file, e.g. raw-data/<table>/<date>.csv).
--   * dataset.quarantine_record holds ONLY rows that still need fixing: one live row per
--     problem row (table, source_file, source_row_number). The analyst edits raw_record in place
--     (astra fix set); every edit is logged in dataset.quarantine_edit with the old value.
--   * Each ETL run rechecks every quarantine row together with the rows of new files.
--     A row that passes is loaded into its table, copied to dataset.quarantine_archive
--     (resolution GRADUATED, metadata only) and deleted from quarantine. A row that still fails
--     keeps its place with refreshed labels.
--   * Exact duplicates are not loaded and go straight to the archive (DUPLICATE_DROPPED).
--     astra fix drop removes a row that should never load (archive resolution DROPPED).
-- History of 0006/0007 is moved, not lost: SUPERSEDED / GRADUATED / DISMISSED records are copied
-- to the archive and then removed from quarantine.
-- astra_analyst gets DELETE on dataset.quarantine_record only. Business tables stay insert/update.

-- 1. File registry ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dataset.source_file (
  file_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  table_name   text NOT NULL CHECK (table_name ~ '^[a-z_]{1,40}$'),
  file_name    text NOT NULL CHECK (file_name ~ '^[A-Za-z0-9_./-]{1,200}$' AND file_name !~ '\.\.'),
  file_sha256  char(64) NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
  rows_read    integer NOT NULL CHECK (rows_read >= 0),
  run_id       uuid NOT NULL REFERENCES dataset.etl_run (run_id),
  ingested_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (table_name, file_name),
  UNIQUE (table_name, file_sha256)
);
COMMENT ON TABLE dataset.source_file IS 'Every source file the ETL has read. A registered file is never read again.';

-- The files loaded before this migration: the latest successful run read them.
INSERT INTO dataset.source_file (table_name, file_name, file_sha256, rows_read, run_id, ingested_at)
SELECT f.table_name, f.file_name, f.file_sha256, f.rows_read, f.run_id, r.started_at
FROM dataset.etl_run_file f
JOIN dataset.etl_run r ON r.run_id = f.run_id
WHERE f.run_id = (SELECT run_id FROM dataset.etl_run WHERE status = 'SUCCEEDED'
                  ORDER BY started_at DESC LIMIT 1)
ON CONFLICT DO NOTHING;

-- One run may now read several files of the same table.
ALTER TABLE dataset.etl_run_file DROP CONSTRAINT IF EXISTS etl_run_file_pkey;
ALTER TABLE dataset.etl_run_file ADD CONSTRAINT etl_run_file_pkey PRIMARY KEY (run_id, table_name, file_name);

-- 2. Archive (metadata only: no raw values) -----------------------------------------------------
CREATE TABLE IF NOT EXISTS dataset.quarantine_archive (
  archive_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  quarantine_id     bigint,  -- NULL for duplicates that never entered quarantine
  table_name        text NOT NULL CHECK (table_name ~ '^[a-z_]{1,40}$'),
  source_file       text CHECK (char_length(source_file) <= 200),
  source_row_number integer CHECK (source_row_number >= 1),
  record_key        text CHECK (char_length(record_key) <= 64),
  rule_id           text NOT NULL REFERENCES dataset.quarantine_rule (rule_id),
  issue_code        text NOT NULL CHECK (issue_code ~ '^[A-Z0-9_]{1,64}$'),
  failed_columns    text[] NOT NULL DEFAULT '{}',
  depends_on        text CHECK (char_length(depends_on) <= 100),
  edited_columns    text[] NOT NULL DEFAULT '{}',
  first_run_id      uuid REFERENCES dataset.etl_run (run_id),
  created_at        timestamptz,
  resolution        text NOT NULL CHECK (resolution IN ('GRADUATED', 'DUPLICATE_DROPPED', 'DROPPED', 'SUPERSEDED')),
  resolved_run_id   uuid REFERENCES dataset.etl_run (run_id),
  resolved_at       timestamptz NOT NULL DEFAULT now(),
  resolved_by       text NOT NULL DEFAULT current_user CHECK (char_length(resolved_by) <= 64),
  note              text CHECK (char_length(note) <= 300)
);
COMMENT ON TABLE dataset.quarantine_archive IS
  'Rows that left quarantine: GRADUATED (loaded), DUPLICATE_DROPPED, DROPPED (by an analyst), SUPERSEDED (legacy per-run copy). No raw values.';
CREATE INDEX IF NOT EXISTS quarantine_archive_table_idx ON dataset.quarantine_archive (table_name, resolution);
CREATE INDEX IF NOT EXISTS quarantine_archive_run_idx ON dataset.quarantine_archive (resolved_run_id);

-- 3. Edit log ---------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dataset.quarantine_edit (
  edit_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  quarantine_id        bigint,  -- no FK: the quarantine row is deleted when it graduates
  table_name           text NOT NULL CHECK (table_name ~ '^[a-z_]{1,40}$'),
  source_file          text CHECK (char_length(source_file) <= 200),
  source_row_number    integer CHECK (source_row_number >= 1),
  record_key           text CHECK (char_length(record_key) <= 64),
  column_name          text NOT NULL CHECK (column_name ~ '^[a-z_]{1,64}$'),
  old_value            text CHECK (char_length(old_value) <= 500),
  new_value            text CHECK (char_length(new_value) <= 500),  -- NULL = made blank
  reason               text NOT NULL CHECK (char_length(reason) BETWEEN 3 AND 300),
  edited_by            text NOT NULL DEFAULT current_user CHECK (char_length(edited_by) <= 64),
  edited_at            timestamptz NOT NULL DEFAULT now(),
  legacy_correction_id bigint
);
COMMENT ON TABLE dataset.quarantine_edit IS 'Every analyst edit of a quarantined value (old and new value). May hold PII.';
CREATE INDEX IF NOT EXISTS quarantine_edit_record_idx ON dataset.quarantine_edit (table_name, upper(record_key));

-- 0007 corrections become edit-log history (old value unknown: the overlay never stored it).
INSERT INTO dataset.quarantine_edit (table_name, source_file, source_row_number, record_key, column_name,
                                     old_value, new_value, reason, edited_by, edited_at, legacy_correction_id)
SELECT c.table_name, c.table_name || '.csv', c.source_row_number, upper(c.record_key), c.column_name,
       NULL, c.corrected_value, c.reason, c.corrected_by, c.created_at, c.correction_id
FROM dataset.quarantine_correction c
WHERE NOT EXISTS (SELECT 1 FROM dataset.quarantine_edit e WHERE e.legacy_correction_id = c.correction_id);
COMMENT ON TABLE dataset.quarantine_correction IS
  'LEGACY (0007), read-only. The ETL no longer reads it; history copied to dataset.quarantine_edit.';
REVOKE INSERT, UPDATE ON dataset.quarantine_correction FROM astra_analyst;
DROP POLICY IF EXISTS analyst_insert ON dataset.quarantine_correction;
DROP POLICY IF EXISTS analyst_update ON dataset.quarantine_correction;

-- 4. Quarantine becomes live rows only ----------------------------------------------------------
ALTER TABLE dataset.quarantine_record
  ADD COLUMN IF NOT EXISTS source_file         text CHECK (char_length(source_file) <= 200),
  ADD COLUMN IF NOT EXISTS last_checked_run_id uuid REFERENCES dataset.etl_run (run_id),
  ADD COLUMN IF NOT EXISTS last_checked_at     timestamptz;
COMMENT ON COLUMN dataset.quarantine_record.corrected_columns IS 'Source columns an analyst edited (astra fix set).';
COMMENT ON COLUMN dataset.quarantine_record.raw_record IS 'Source row as edited by analysts; rechecked by every ETL run. May hold PII.';
COMMENT ON COLUMN dataset.quarantine_record.run_id IS 'Run that first quarantined the row.';

-- Move history to the archive, then remove it from quarantine.
INSERT INTO dataset.quarantine_archive (quarantine_id, table_name, source_file, source_row_number, record_key,
       rule_id, issue_code, failed_columns, depends_on, edited_columns, first_run_id, created_at,
       resolution, resolved_run_id, resolved_at, resolved_by, note)
SELECT q.quarantine_id, q.table_name, q.table_name || '.csv', q.source_row_number, q.record_key,
       q.rule_id, q.issue_code, q.failed_columns, q.depends_on, q.corrected_columns, q.run_id, q.created_at,
       CASE WHEN q.status = 'GRADUATED' THEN 'GRADUATED'
            WHEN q.status = 'SUPERSEDED' THEN 'SUPERSEDED'
            WHEN q.rule_id = 'EXACT_DUPLICATE_ROW' THEN 'DUPLICATE_DROPPED'
            ELSE 'DROPPED' END,
       q.resolved_run_id, coalesce(q.resolved_at, now()), 'migration_0008',
       CASE WHEN q.status = 'DISMISSED' AND q.rule_id <> 'EXACT_DUPLICATE_ROW' THEN 'row left the source file (0006)' END
FROM dataset.quarantine_record q
WHERE q.status <> 'OPEN';
DELETE FROM dataset.quarantine_record WHERE status <> 'OPEN';

UPDATE dataset.quarantine_record SET source_file = table_name || '.csv' WHERE source_file IS NULL;
ALTER TABLE dataset.quarantine_record ALTER COLUMN source_file SET NOT NULL;
ALTER TABLE dataset.quarantine_record DROP CONSTRAINT IF EXISTS quarantine_record_status_lifecycle;
ALTER TABLE dataset.quarantine_record ADD CONSTRAINT quarantine_record_status_lifecycle CHECK (status = 'OPEN');
CREATE UNIQUE INDEX IF NOT EXISTS quarantine_record_source_row_uq
  ON dataset.quarantine_record (table_name, source_file, source_row_number);

-- 5. Rule catalog: fixes are made in quarantine, not in the source file ---------------------------
ALTER TABLE dataset.quarantine_rule DROP CONSTRAINT IF EXISTS quarantine_rule_graduation_path_check;
UPDATE dataset.quarantine_rule SET graduation_path = 'FIX_IN_QUARANTINE' WHERE graduation_path = 'FIX_SOURCE';
ALTER TABLE dataset.quarantine_rule ADD CONSTRAINT quarantine_rule_graduation_path_check
  CHECK (graduation_path IN ('FIX_IN_QUARANTINE', 'AUTO_WITH_PARENT', 'NOT_NEEDED'));

INSERT INTO dataset.quarantine_rule (rule_id, issue_code, decision, graduation_path, description, remediation) VALUES
  ('REQUIRED_FIELD_MISSING', 'MISSING_REQUIRED_FIELD', NULL, 'FIX_IN_QUARANTINE',
   'Required value is blank or a placeholder (N/A, NA, NULL, NONE, -, UNKNOWN, TBD).',
   'Fill in the real value with astra fix set; the next ETL run rechecks the row.'),
  ('DATE_FORMAT_INVALID', 'INVALID_DATE_FORMAT', 'D1', 'FIX_IN_QUARANTINE',
   'Date or time is not in an accepted format or is not a real calendar date.',
   'Set the date as YYYY-MM-DD (time as HH:MM) with astra fix set.'),
  ('NUMERIC_VALUE_INVALID', 'INVALID_NUMERIC_VALUE', 'D3', 'FIX_IN_QUARANTINE',
   'Number cannot be parsed, is a word, or is out of range (quantity <= 0, percent outside 0-100).',
   'Set a valid number in range with astra fix set.'),
  ('CATEGORY_VALUE_INVALID', 'INVALID_CATEGORY', NULL, 'FIX_IN_QUARANTINE',
   'Value is outside the allowed set, or an identifier has an invalid format.',
   'Set one of the allowed values (docs/30-database-schema.md) with astra fix set.'),
  ('NEGATIVE_AMOUNT', 'BUSINESS_RULE_VIOLATION', 'D4', 'FIX_IN_QUARANTINE',
   'Money amount (price, cost, salary, expense) is negative.',
   'Set the correct non-negative amount with astra fix set. Refunds need their own record type.'),
  ('MANAGER_IS_SELF', 'BUSINESS_RULE_VIOLATION', NULL, 'FIX_IN_QUARANTINE',
   'Employee is listed as their own manager.',
   'Set the correct manager_id, or blank it (D6), with astra fix set.'),
  ('WAREHOUSE_CODE_FORMAT', 'INVALID_CATEGORY', NULL, 'FIX_IN_QUARANTINE',
   'Warehouse code does not match WH-AAA-00.',
   'Set a code like WH-AAA-00 with astra fix set.'),
  ('CHECKOUT_BEFORE_CHECKIN', 'BUSINESS_RULE_VIOLATION', NULL, 'FIX_IN_QUARANTINE',
   'Attendance check_out is earlier than check_in.',
   'Correct check_in or check_out with astra fix set.'),
  ('DUPLICATE_PRIMARY_KEY', 'DUPLICATE_PRIMARY_KEY', 'D5', 'FIX_IN_QUARANTINE',
   'Same primary key as a row already loaded (earlier in the file or from an earlier file) but different content.',
   'Give this row its own key with astra fix set, or remove it with astra fix drop if the loaded row is correct.'),
  ('ORPHAN_PARENT_QUARANTINED', 'ORPHAN_FOREIGN_KEY', NULL, 'AUTO_WITH_PARENT',
   'Referenced parent row is itself in quarantine.',
   'Fix the parent named in depends_on; this row graduates on the same run.'),
  ('ORPHAN_KEY_NOT_IN_SOURCE', 'ORPHAN_FOREIGN_KEY', NULL, 'FIX_IN_QUARANTINE',
   'Referenced key is not loaded and not in quarantine.',
   'Graduates by itself when a later file brings the parent; otherwise correct or blank the key with astra fix set.'),
  ('EXACT_DUPLICATE_ROW', 'EXACT_DUPLICATE_ROW', 'D5', 'NOT_NEEDED',
   'Exact copy of a row already loaded or already in quarantine.',
   'No action. Not loaded; archived as DUPLICATE_DROPPED.')
ON CONFLICT (rule_id) DO UPDATE SET
  issue_code = EXCLUDED.issue_code, decision = EXCLUDED.decision,
  graduation_path = EXCLUDED.graduation_path, description = EXCLUDED.description,
  remediation = EXCLUDED.remediation;

-- 6. Views ----------------------------------------------------------------------------------
-- Lifecycle counts: open rows (live) plus everything that left quarantine (archive).
CREATE OR REPLACE VIEW dataset.v_quarantine_lifecycle WITH (security_invoker = true) AS
SELECT q.table_name, q.rule_id, r.graduation_path, 'OPEN'::text AS status,
       count(*) AS records, max(coalesce(q.last_checked_at, q.created_at)) AS last_change_at
FROM dataset.quarantine_record q
JOIN dataset.quarantine_rule r ON r.rule_id = q.rule_id
GROUP BY q.table_name, q.rule_id, r.graduation_path
UNION ALL
SELECT a.table_name, a.rule_id, r.graduation_path, a.resolution,
       count(*), max(a.resolved_at)
FROM dataset.quarantine_archive a
JOIN dataset.quarantine_rule r ON r.rule_id = a.rule_id
GROUP BY a.table_name, a.rule_id, r.graduation_path, a.resolution;

-- 7. Access ---------------------------------------------------------------------------------
ALTER TABLE dataset.source_file ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset.quarantine_archive ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset.quarantine_edit ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON dataset.source_file, dataset.quarantine_archive, dataset.quarantine_edit
  FROM PUBLIC, anon, authenticated;

-- Analyst: append-only on the three new tables.
GRANT SELECT, INSERT ON dataset.source_file, dataset.quarantine_archive, dataset.quarantine_edit TO astra_analyst;
DROP POLICY IF EXISTS analyst_select ON dataset.source_file;
DROP POLICY IF EXISTS analyst_insert ON dataset.source_file;
DROP POLICY IF EXISTS analyst_select ON dataset.quarantine_archive;
DROP POLICY IF EXISTS analyst_insert ON dataset.quarantine_archive;
DROP POLICY IF EXISTS analyst_select ON dataset.quarantine_edit;
DROP POLICY IF EXISTS analyst_insert ON dataset.quarantine_edit;
CREATE POLICY analyst_select ON dataset.source_file FOR SELECT TO astra_analyst USING (true);
CREATE POLICY analyst_insert ON dataset.source_file FOR INSERT TO astra_analyst WITH CHECK (true);
CREATE POLICY analyst_select ON dataset.quarantine_archive FOR SELECT TO astra_analyst USING (true);
CREATE POLICY analyst_insert ON dataset.quarantine_archive FOR INSERT TO astra_analyst WITH CHECK (true);
CREATE POLICY analyst_select ON dataset.quarantine_edit FOR SELECT TO astra_analyst USING (true);
CREATE POLICY analyst_insert ON dataset.quarantine_edit FOR INSERT TO astra_analyst WITH CHECK (true);

-- Analyst may delete quarantine rows (graduate / drop). No other table gets DELETE.
GRANT DELETE ON dataset.quarantine_record TO astra_analyst;
DROP POLICY IF EXISTS analyst_delete ON dataset.quarantine_record;
CREATE POLICY analyst_delete ON dataset.quarantine_record FOR DELETE TO astra_analyst USING (true);

GRANT USAGE ON ALL SEQUENCES IN SCHEMA dataset TO astra_analyst;

-- Reporting: no keys, values, reasons or authors.
DROP POLICY IF EXISTS reporting_select ON dataset.source_file;
DROP POLICY IF EXISTS reporting_select ON dataset.quarantine_archive;
DROP POLICY IF EXISTS reporting_select ON dataset.quarantine_edit;
CREATE POLICY reporting_select ON dataset.source_file FOR SELECT TO astra_reporting USING (true);
CREATE POLICY reporting_select ON dataset.quarantine_archive FOR SELECT TO astra_reporting USING (true);
CREATE POLICY reporting_select ON dataset.quarantine_edit FOR SELECT TO astra_reporting USING (true);
GRANT SELECT ON dataset.source_file TO astra_reporting;
GRANT SELECT (archive_id, table_name, source_file, rule_id, issue_code, failed_columns, edited_columns,
              first_run_id, created_at, resolution, resolved_run_id, resolved_at)
  ON dataset.quarantine_archive TO astra_reporting;
GRANT SELECT (edit_id, table_name, column_name, edited_at) ON dataset.quarantine_edit TO astra_reporting;
GRANT SELECT (source_file, last_checked_run_id, last_checked_at) ON dataset.quarantine_record TO astra_reporting;
