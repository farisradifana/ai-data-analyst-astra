# 31 — ETL and quarantine lifecycle

## Run

Run these from the project folder, in PowerShell or cmd.
`astra.cmd` sets `PYTHONPATH` itself.

```powershell
.\astra etl --dry-run
```
```powershell
.\astra etl --dry-run --offline
```
```powershell
.\astra etl
```

- The first command validates and reads fixes, but writes nothing to the database.
- The second skips the database entirely.
- The third loads the data as `astra_analyst`, over `verify-full` SSL.
- Running `.\astra` with no command only prints the usage. It never starts a load.

The run reads `raw-data/<table>.csv` and connects with `.env` (see doc 30 and `scripts/check_db_connection.py`).
It writes a counts-only summary to `reports/etl/last_run_summary.{json,md}`, which contains no record content.
A full load takes about 100 s.

Modules in `src/astra_etl/`:

| Module | Role |
|---|---|
| `clean.py` | Value cleaners. Decisions D1–D4, D6. |
| `spec.py` | Mapping per table (CSV column → cleaner → DB column), FKs, cross-column rules |
| `rules.py` | Quarantine rule catalog. Mirrors `dataset.quarantine_rule`. |
| `fix.py` | `.\astra fix` commands: list / show / set / off / status for fixes |
| `transform.py` | Exact duplicates, cleaning, row rules, PK conflicts, FK checks. Asserts `read = loaded + quarantined + duplicate`. |
| `load.py` | One transaction. Upserts with no DELETE, then the quarantine lifecycle, `etl_run_file` and `dq_check_result`. |

## Decision: strict quarantine (2026-11-17)

Products with a negative `list_price` (32) or a missing one (38) stay quarantined.
Every fact row that references them is quarantined too, with rule `ORPHAN_PARENT_QUARANTINED`.
That is 2,994 sales, 250 service orders, 421 procurement rows and 499 inventory rows.
They are not loaded with a NULL price.

## Every row is labelled

Each quarantined or duplicate row in `dataset.quarantine_record` carries these labels:

- **`rule_id`**: one rule from `dataset.quarantine_rule`. The rule holds the description, the D-decision and the remediation.
- **`failed_columns`**: the column names to fix. Values are never stored here.
- **`depends_on`**: what the row waits for, either `products:PRD00012` or `row:<source line>` of the row that was kept.
- **`raw_record`**: the original source row, so it can be fixed and reprocessed. It may contain PII and is analyst-only.

| rule_id | graduation_path | Meaning |
|---|---|---|
| REQUIRED_FIELD_MISSING | FIX_SOURCE | Required value is blank, or a placeholder such as N/A or TBD |
| DATE_FORMAT_INVALID | FIX_SOURCE | Date or time is not valid (D1) |
| NUMERIC_VALUE_INVALID | FIX_SOURCE | Not a number, a word, or out of range (D3) |
| CATEGORY_VALUE_INVALID | FIX_SOURCE | Value is outside the allowed set |
| NEGATIVE_AMOUNT | FIX_SOURCE | Negative money amount (D4) |
| MANAGER_IS_SELF | FIX_SOURCE | Employee is listed as their own manager |
| WAREHOUSE_CODE_FORMAT | FIX_SOURCE | Code is not `WH-AAA-00` |
| CHECKOUT_BEFORE_CHECKIN | FIX_SOURCE | Check-out time is earlier than check-in |
| DUPLICATE_PRIMARY_KEY | FIX_SOURCE | Same key as an earlier row but different content (D5) |
| ORPHAN_PARENT_QUARANTINED | AUTO_WITH_PARENT | Parent row exists but is quarantined |
| ORPHAN_KEY_NOT_IN_SOURCE | FIX_SOURCE | Parent key is not in the source at all |
| EXACT_DUPLICATE_ROW | NOT_NEEDED | Identical copy. The first copy loaded. Kept for audit. |

## How a row graduates to valid data

Fix quarantined data in the database, not in the CSV.
Each fix is one cell, stored in `dataset.quarantine_correction` (migration 0007).
Every ETL run applies the active fixes on top of the raw row, then validates it again.
The source files in `raw-data/` are never changed, so they stay as the audit trail.

1. **Find** what to fix. `list` shows table, key, rule, the columns to fix and what the row waits for.
   It shows no values.

   ```powershell
   .\astra fix list --table products
   ```

2. **Look** at one row: its rule, how to fix it, and the current values.
   The failing columns are marked `<-`.
   The output can contain personal data, so use it on your own machine only.

   ```powershell
   .\astra fix show products PRD00148
   ```

3. **Fix** the value. Use the column name from the source CSV. `--reason` is required.

   ```powershell
   .\astra fix set products PRD00148 list_price 150000 --reason "price from catalogue"
   ```

   - `--blank` makes the cell empty instead of setting a value.
   - `--line N` limits the fix to one source line. Use it when two rows share a key (`DUPLICATE_PRIMARY_KEY`).
     For example, give the second row a new key with `set sales_transactions SAL00000004 transaction_id SAL00000009 --line 8`.
   - Setting the same cell again replaces the earlier fix.
   - `off <correction_id>` withdraws a fix. Rows are never deleted: the fix is only marked inactive.
   - For `AUTO_WITH_PARENT` rows, fix the parent named in `depends_on`.
     All the rows waiting on that parent graduate in the same run.
4. **Rerun** the ETL with `.\astra etl`.
   Put double quotes around any value that contains spaces, commas or `=`.
   Each fix gets a `last_outcome`:

   | Outcome | Meaning |
   |---|---|
   | `LOADED` | The fixed row passed validation and is in the valid table |
   | `STILL_QUARANTINED` | The fixed row still fails |
   | `KEY_NOT_FOUND` | No source row has that key |
   | `COLUMN_UNKNOWN` | The table has no column with that name |

   The earlier OPEN quarantine records change status:
   - `GRADUATED`: the key is now loaded into the valid table.
   - `SUPERSEDED`: the key still fails. A new OPEN record replaces it, possibly under a different rule, and its `corrected_columns` shows what was fixed.
   - `DISMISSED`: the row is no longer in the source file.

   `resolved_run_id` records which run made the change.
5. **Track** progress:
   - `.\astra fix status`, or the view `v_correction_status`.
   - `v_quarantine_lifecycle`, which counts records per table, rule and status.

Fixes are kept across runs.
A fix also overrides a value that was later corrected in the CSV, until you withdraw it.
A row with a blank primary key cannot be fixed this way. Fix it in the CSV instead.

**Access:**
- `astra_analyst` (the `fix` command) can read and write fixes.
- `astra_reporting` sees only the fix metadata: table, column, active flag, outcome and dates.
  It does not see the key, the value, the reason or the author.
- Edits made in the Supabase table editor run as `postgres`. The ETL picks them up the same way.

**End-to-end check (2026-11-18):**
- The check ran in one transaction that was rolled back, so no data changed.
- One fix set `list_price` for product `PRD00148`.
- The product and the 69 rows waiting only on it went from OPEN to GRADUATED.
- The fix's outcome was `LOADED`.
- After the rollback, no `etl_run` row and no fix row remained.

## First load (2026-11-17)

| | Rows |
|---|---:|
| Read | 435,200 |
| Loaded | 428,516 |
| Quarantined (OPEN) | 5,984 |
| Exact duplicates (DISMISSED) | 700 |

Open records by rule:

| Rule | Open records |
|---|---:|
| ORPHAN_PARENT_QUARANTINED | 4,164 |
| ORPHAN_KEY_NOT_IN_SOURCE | 1,153 |
| NUMERIC_VALUE_INVALID | 337 |
| REQUIRED_FIELD_MISSING | 251 |
| NEGATIVE_AMOUNT | 79 |

All 10 tables reconcile against `v_etl_run_summary` when checked as `astra_reporting`.
`astra_reporting` is denied `depends_on`, `raw_record` and `record_key`.
A second identical run kept the table counts unchanged.
It moved the 5,984 earlier OPEN records to SUPERSEDED.

## Known limits

- Each run inserts its OPEN and duplicate records again, which adds about 6,700 rows per run.
  A retention policy, for example archiving SUPERSEDED and DISMISSED records older than N days, is still to do.
- A row loaded by an earlier run that fails now stays in its table, because the ETL role has no DELETE privilege.
  Its `etl_run_id` is older than the latest run.
- The GRADUATED path was checked once, end to end, in a transaction that was rolled back (see above).
  It has not yet been used on committed data.
