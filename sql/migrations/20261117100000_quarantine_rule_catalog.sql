-- 0006 — Quarantine rule catalog and graduation lifecycle.
--
-- Every quarantined or duplicate row is labelled with one rule_id from dataset.quarantine_rule,
-- the columns that failed (failed_columns) and the row it waits for (depends_on), so it can be
-- fixed later and graduate to valid data.
--   status OPEN        still failing, needs the remediation in its rule
--          GRADUATED   a later run loaded this key into the valid table
--          SUPERSEDED  a later run quarantined this key again (newer OPEN record replaces it)
--          DISMISSED   no action needed (exact duplicate) or the row left the source file
-- Applied while dataset.quarantine_record was empty (no ETL run yet), so NOT NULL is safe.
-- Rule rows mirror src/astra_etl/rules.py (kept in sync by tests/etl/test_rules.py).

CREATE TABLE IF NOT EXISTS dataset.quarantine_rule (
  rule_id         text PRIMARY KEY CHECK (rule_id ~ '^[A-Z0-9_]{1,64}$'),
  issue_code      text NOT NULL CHECK (issue_code ~ '^[A-Z0-9_]{1,64}$'),
  decision        text CHECK (decision ~ '^D[0-9]{1,2}$'),
  graduation_path text NOT NULL CHECK (graduation_path IN ('FIX_SOURCE', 'AUTO_WITH_PARENT', 'NOT_NEEDED')),
  description     text NOT NULL CHECK (char_length(description) <= 300),
  remediation     text NOT NULL CHECK (char_length(remediation) <= 300)
);
COMMENT ON TABLE dataset.quarantine_rule IS 'Catalog of DQ rules. Explains why a row was quarantined and how it graduates to valid data.';

INSERT INTO dataset.quarantine_rule (rule_id, issue_code, decision, graduation_path, description, remediation) VALUES
  ('REQUIRED_FIELD_MISSING', 'MISSING_REQUIRED_FIELD', NULL, 'FIX_SOURCE',
   'Required value is blank or a placeholder (N/A, NA, NULL, NONE, -, UNKNOWN, TBD).',
   'Fill in the real value in the source file, then rerun the ETL.'),
  ('DATE_FORMAT_INVALID', 'INVALID_DATE_FORMAT', 'D1', 'FIX_SOURCE',
   'Date or time is not in an accepted format or is not a real calendar date.',
   'Write the date as YYYY-MM-DD (time as HH:MM), then rerun.'),
  ('NUMERIC_VALUE_INVALID', 'INVALID_NUMERIC_VALUE', 'D3', 'FIX_SOURCE',
   'Number cannot be parsed, is a word, or is out of range (quantity <= 0, percent outside 0-100).',
   'Enter a valid number in range, then rerun.'),
  ('CATEGORY_VALUE_INVALID', 'INVALID_CATEGORY', NULL, 'FIX_SOURCE',
   'Value is outside the allowed set, or an identifier has an invalid format.',
   'Use one of the allowed values listed in docs/30-database-schema.md, then rerun.'),
  ('NEGATIVE_AMOUNT', 'BUSINESS_RULE_VIOLATION', 'D4', 'FIX_SOURCE',
   'Money amount (price, cost, salary, expense) is negative.',
   'Enter the correct non-negative amount, then rerun. Refunds need their own record type.'),
  ('MANAGER_IS_SELF', 'BUSINESS_RULE_VIOLATION', NULL, 'FIX_SOURCE',
   'Employee is listed as their own manager.',
   'Set the correct manager_id, or leave it blank (D6), then rerun.'),
  ('WAREHOUSE_CODE_FORMAT', 'INVALID_CATEGORY', NULL, 'FIX_SOURCE',
   'Warehouse code does not match WH-AAA-00.',
   'Correct the warehouse code, then rerun.'),
  ('CHECKOUT_BEFORE_CHECKIN', 'BUSINESS_RULE_VIOLATION', NULL, 'FIX_SOURCE',
   'Attendance check_out is earlier than check_in.',
   'Correct the check-in or check-out time, then rerun.'),
  ('DUPLICATE_PRIMARY_KEY', 'DUPLICATE_PRIMARY_KEY', 'D5', 'FIX_SOURCE',
   'Same primary key as an earlier row but different content; the earlier row was loaded.',
   'Give this row its own key, or remove it if the earlier row is correct (see depends_on), then rerun.'),
  ('ORPHAN_PARENT_QUARANTINED', 'ORPHAN_FOREIGN_KEY', NULL, 'AUTO_WITH_PARENT',
   'Referenced parent row exists in the source but is itself quarantined.',
   'Fix the parent row named in depends_on; this row graduates on the same rerun.'),
  ('ORPHAN_KEY_NOT_IN_SOURCE', 'ORPHAN_FOREIGN_KEY', NULL, 'FIX_SOURCE',
   'Referenced key does not exist in the parent source file.',
   'Add the missing parent row, correct the key, or blank it if the column allows it, then rerun.'),
  ('EXACT_DUPLICATE_ROW', 'EXACT_DUPLICATE_ROW', 'D5', 'NOT_NEEDED',
   'Exact copy of an earlier row in the same file; the first copy was loaded.',
   'No action. Kept for audit; status is DISMISSED on insert.')
ON CONFLICT (rule_id) DO UPDATE SET
  issue_code = EXCLUDED.issue_code, decision = EXCLUDED.decision,
  graduation_path = EXCLUDED.graduation_path, description = EXCLUDED.description,
  remediation = EXCLUDED.remediation;

-- Label columns on quarantine_record.
ALTER TABLE dataset.quarantine_record
  ADD COLUMN IF NOT EXISTS rule_id        text   NOT NULL REFERENCES dataset.quarantine_rule (rule_id),
  ADD COLUMN IF NOT EXISTS failed_columns text[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS depends_on     text   CHECK (char_length(depends_on) <= 100);
COMMENT ON COLUMN dataset.quarantine_record.rule_id IS 'Rule that put the row here; see dataset.quarantine_rule.remediation.';
COMMENT ON COLUMN dataset.quarantine_record.failed_columns IS 'Columns that must be fixed (names only, no values).';
COMMENT ON COLUMN dataset.quarantine_record.depends_on IS 'What the row waits for: <parent_table>:<key> or row:<source line of the kept row>.';

-- Lifecycle statuses (replaces OPEN / REPROCESSED / DISMISSED; table was empty).
DO $$
DECLARE c text;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'dataset.quarantine_record'::regclass AND contype = 'c'
             AND pg_get_constraintdef(oid) LIKE '%REPROCESSED%'
  LOOP
    EXECUTE format('ALTER TABLE dataset.quarantine_record DROP CONSTRAINT %I', c);
  END LOOP;
END
$$;
ALTER TABLE dataset.quarantine_record DROP CONSTRAINT IF EXISTS quarantine_record_status_lifecycle;
ALTER TABLE dataset.quarantine_record ADD CONSTRAINT quarantine_record_status_lifecycle
  CHECK (status IN ('OPEN', 'GRADUATED', 'SUPERSEDED', 'DISMISSED'));

CREATE INDEX IF NOT EXISTS quarantine_record_rule_idx ON dataset.quarantine_record (rule_id, status);
CREATE INDEX IF NOT EXISTS quarantine_record_open_key_idx
  ON dataset.quarantine_record (table_name, record_key) WHERE status = 'OPEN';

-- Access: same model as 0004. Catalog has no PII; writes only through migrations.
ALTER TABLE dataset.quarantine_rule ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON dataset.quarantine_rule FROM PUBLIC, anon, authenticated;
GRANT SELECT ON dataset.quarantine_rule TO astra_analyst, astra_reporting;
DROP POLICY IF EXISTS analyst_select ON dataset.quarantine_rule;
DROP POLICY IF EXISTS reporting_select ON dataset.quarantine_rule;
CREATE POLICY analyst_select ON dataset.quarantine_rule FOR SELECT TO astra_analyst USING (true);
CREATE POLICY reporting_select ON dataset.quarantine_rule FOR SELECT TO astra_reporting USING (true);

-- Reporting may see the labels (column names only). depends_on holds record keys: not granted.
GRANT SELECT (rule_id, failed_columns) ON dataset.quarantine_record TO astra_reporting;

-- Open quarantine by rule (columns appended, existing ones unchanged).
CREATE OR REPLACE VIEW dataset.v_quarantine_open WITH (security_invoker = true) AS
SELECT q.table_name, q.issue_code, q.suggested_category,
       count(*)          AS open_records,
       min(q.created_at) AS oldest_created_at,
       q.rule_id, r.graduation_path, r.remediation
FROM dataset.quarantine_record q
JOIN dataset.quarantine_rule r ON r.rule_id = q.rule_id
WHERE q.status = 'OPEN'
GROUP BY q.table_name, q.issue_code, q.suggested_category, q.rule_id, r.graduation_path, r.remediation;

-- Lifecycle counts: how many records per rule are open, graduated, superseded, dismissed.
CREATE OR REPLACE VIEW dataset.v_quarantine_lifecycle WITH (security_invoker = true) AS
SELECT q.table_name, q.rule_id, r.graduation_path, q.status,
       count(*) AS records, max(coalesce(q.resolved_at, q.created_at)) AS last_change_at
FROM dataset.quarantine_record q
JOIN dataset.quarantine_rule r ON r.rule_id = q.rule_id
GROUP BY q.table_name, q.rule_id, r.graduation_path, q.status;

REVOKE ALL ON dataset.v_quarantine_open, dataset.v_quarantine_lifecycle FROM PUBLIC, anon, authenticated;
GRANT SELECT ON dataset.v_quarantine_open, dataset.v_quarantine_lifecycle TO astra_analyst, astra_reporting;
