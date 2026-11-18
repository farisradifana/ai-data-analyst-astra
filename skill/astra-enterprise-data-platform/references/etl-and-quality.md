# ETL and data quality standards

## Run flow

1. **Lock**: session advisory lock, one run at a time.
2. **Read state**: registered files (name + SHA-256), open quarantine rows, loaded primary keys.
3. **Read new files only**: `raw-data/<table>.csv`, then `raw-data/<table>/*.csv` by name. Other names are ignored.
   A registered file whose checksum changed stops the run. Same content under a new name is skipped.
4. **Clean** each column with its cleaner; **validate** row rules; resolve **foreign keys** (parents first,
   self-references cascade); detect **duplicates** against the file and the database.
5. **Recheck quarantine**: every open row, with its edits, goes through the same pipeline.
6. **Load** in one transaction: insert passing rows, archive graduated and duplicate quarantine rows, refresh labels
   of rows still failing, insert new failures, register files, write `etl_run_file` and `dq_check_result`.
7. **Reconcile**: per file `read = loaded + quarantined + duplicate`; per table
   `rechecked = graduated + still open + dropped as duplicate`. A mismatch stops the run.
8. **Summary** (counts only) to `reports/etl/last_run_summary.*`; **alerts** after a real load.

Any error → ROLLBACK, `etl_run` marked FAILED with the error class only.

## Cleaning standards

- Text: trim, collapse spaces. Placeholders `''`, `N/A`, `NA`, `NULL`, `NONE`, `-`, `UNKNOWN`, `TBD` (any case) = blank.
- Codes/categories: upper-case, must be in an explicit allowed set. Map known variants (e.g. `NET 30`, `30 DAYS` → `NET30`).
- Dates: accept only known formats; ambiguous formats need a documented decision (Astra D1: `NN/NN/YYYY` day-first,
  `NN-NN-YYYY` month-first). Impossible dates are rejected, never shifted.
- Money: strip currency and thousands separators; reject words; negatives rejected unless refunds are modelled.
- Quantities: integers > 0; words like `two` rejected, never converted.
- Identifiers and phone numbers stay text (leading zeros).
- PII placeholders become NULL where the column is nullable.

## Rule catalog (Astra)

| Rule id | Issue code | Graduates by |
|---|---|---|
| REQUIRED_FIELD_MISSING | MISSING_REQUIRED_FIELD | fix |
| DATE_FORMAT_INVALID | INVALID_DATE_FORMAT | fix |
| NUMERIC_VALUE_INVALID | INVALID_NUMERIC_VALUE | fix |
| CATEGORY_VALUE_INVALID | INVALID_CATEGORY | fix |
| NEGATIVE_AMOUNT | BUSINESS_RULE_VIOLATION | fix |
| MANAGER_IS_SELF | BUSINESS_RULE_VIOLATION | fix |
| WAREHOUSE_CODE_FORMAT | INVALID_CATEGORY | fix |
| CHECKOUT_BEFORE_CHECKIN | BUSINESS_RULE_VIOLATION | fix |
| DUPLICATE_PRIMARY_KEY | DUPLICATE_PRIMARY_KEY | fix (new key) or drop |
| ORPHAN_PARENT_QUARANTINED | ORPHAN_FOREIGN_KEY | automatically with the parent |
| ORPHAN_KEY_NOT_IN_SOURCE | ORPHAN_FOREIGN_KEY | a later file brings the parent, or fix |
| EXACT_DUPLICATE_ROW | EXACT_DUPLICATE_ROW | not needed (archived as DUPLICATE_DROPPED) |

The catalog lives in Python and in a SQL seed table; a test checks they match.

## Quality rules that always apply

- Never load a row that failed validation. Never guess a value.
- Quarantine detail names columns and codes, never values (values may be PII).
- Keep the raw record for reprocessing; the archive keeps labels only.
- A loaded key is never overwritten by a later file (it is quarantined as DUPLICATE_PRIMARY_KEY).
- Data decisions (dates, duplicates, negatives, blank managers) are written down with an id (D1..Dn) and the user's choice.
