# Testing and reprocessing

## Gates (cheapest first; report each as PASS/FAIL with the command, or "not available")

1. `python -m compileall -q src tests`
2. `.\astra test` (offline unit tests: cleaners, rules, transform, requeue, alerts, n8n workflow, QA cases)
3. `.\astra n8n lint`
4. `.\astra n8n check-live` (database, read-only)
5. `.\astra etl --dry-run --offline` (all raw files, no database)
6. `.\astra etl --dry-run` (live state, writes nothing; a changed registered file fails here)

Use a bounded runner (per-gate timeout, overall deadline, logs) for the full set. Never weaken or skip a test.

## Spec test cases and how they are covered

| # | Case | Test approach |
|---|---|---|
| 1 | Full pipeline | Real load + live reconciliation + offline dry run on all files |
| 2 | Empty source file | Header-only file reads 0 rows; 0-byte file stops with "missing columns" |
| 3 | Duplicate primary key | Exact copy dropped; same key with other values quarantined |
| 4 | Missing required field | Placeholder in a required column → REQUIRED_FIELD_MISSING |
| 5 | Invalid date | Impossible date and unknown format → DATE_FORMAT_INVALID |
| 6 | Invalid numeric value | Word or ≤ 0 quantity → NUMERIC_VALUE_INVALID |
| 7 | Inconsistent category | Messy spelling normalised; value outside the set quarantined |
| 8 | Orphan foreign key | Unknown parent; parent in quarantine cascades; parent in a later file graduates |
| 9 | Invalid business status | Status outside the set; negative amount |
| 10 | DB connection failure | Simulated: run fails, alert names stage and error type, no host |
| 11 | Telegram failure | Retries, gives up after max attempts, never raises into the ETL |
| 12 | Interrupted load | Simulated connection drop mid-load: rollback, run FAILED with error class |
| 13 | Duplicate rerun | Same files again → nothing new; changed file → stop |
| 14 | Reprocessing rejected | Edited parent graduates with children; bad edit stays with a new label |
| 15 | Validation-only | `--dry-run --offline` never connects or alerts |
| 16 | Unauthorized Telegram user | Only testable once a Telegram chat front end exists |
| 17 | Unsafe SQL to AI agent | Lint rejects unsafe SQL; tools are fixed; reporting role cannot write; live chat refusal |

Document any case that cannot run (credentials, connectivity, permissions) as such. Never fabricate a pass.

## Reprocessing procedure

1. `.\astra fix list` (optionally `--table`, `--rule`) to see open rows by rule.
2. `.\astra fix show <table> <key>` to see the row and why it failed.
3. Correct: `.\astra fix set <table> <key> <column> <value> --reason "..."` (or `--blank`; `--id` when keys repeat).
   The old value is logged; `.\astra fix history` lists edits.
4. A row that must never load: `.\astra fix drop <quarantine_id> --reason "..."`.
5. `.\astra etl --dry-run` to preview, then `.\astra etl`. Passing rows graduate (archived as GRADUATED), children
   waiting on them graduate in the same run, rows still failing get refreshed labels.

Re-reading a source file is not the way to reprocess: ingested files are never read again.
