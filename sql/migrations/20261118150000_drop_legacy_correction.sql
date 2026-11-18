-- 0009: drop the legacy correction overlay (0007), unused since 0008.
-- Since 0008, fixes are made inside dataset.quarantine_record (.\astra fix set) and logged in
-- dataset.quarantine_edit. Nothing reads or writes dataset.quarantine_correction anymore, and its rows
-- were copied to quarantine_edit (legacy_correction_id). This migration stops if any row was not copied.
-- Kept: quarantine_record (live rows), quarantine_rule (rule catalog), quarantine_record.corrected_columns.

DO $$
BEGIN
  IF to_regclass('dataset.quarantine_correction') IS NOT NULL AND EXISTS (
       SELECT 1 FROM dataset.quarantine_correction c
       WHERE NOT EXISTS (SELECT 1 FROM dataset.quarantine_edit e WHERE e.legacy_correction_id = c.correction_id)) THEN
    RAISE EXCEPTION 'quarantine_correction has rows not copied to quarantine_edit; not dropping';
  END IF;
END $$;

DROP VIEW IF EXISTS dataset.v_correction_status;
DROP TABLE IF EXISTS dataset.quarantine_correction;

COMMENT ON COLUMN dataset.quarantine_edit.legacy_correction_id IS
  'Id the edit had in the dropped 0007 table quarantine_correction (history only; NULL for edits since 0008).';
