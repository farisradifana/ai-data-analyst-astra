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

- The first command reads the database and validates, but writes nothing.
- The second skips the database entirely and treats every file as new.
- The third loads the data as `astra_analyst`, over `verify-full` SSL.
- Running `.\astra` with no command only prints the usage. It never starts a load.
- Only one load runs at a time. A second one stops with "another ETL run is in progress".

It writes a counts-only summary to `reports/etl/last_run_summary.{json,md}`, which contains no record content.

## How a run works (since migration 0008, 2026-11-18)

**Each source file is read once.**

- Files live in `raw-data/<table>.csv` (the first delivery) and `raw-data/<table>/*.csv` (later deliveries).
- Put each day's file in the table's folder, for example `raw-data/sales_transactions/2026-11-19.csv`.
  Files in a folder are read in name order, so a date name keeps them in order.
- Every file read is registered in `dataset.source_file` with its SHA-256. A registered file is skipped on later runs.
- If a registered file changes, the run stops with an error. Never edit a file that was loaded.
  Restore it, and send new or corrected data as a new file.
- A new file with the same content as a loaded file is skipped.

**Each run, per table (parents first), checks one list of rows:**

1. every row still in quarantine, with the edits made by `.\astra fix set`;
2. the rows of the new files.

Then:

- A row that passes is loaded into its table.
  If it came from quarantine, it is copied to `dataset.quarantine_archive` as `GRADUATED` and deleted from quarantine.
- A quarantined row that still fails stays, with its labels refreshed (rule, columns, `depends_on`, `last_checked_run_id`).
- A new row that fails is added to quarantine.
- An exact duplicate is never loaded. It goes straight to the archive as `DUPLICATE_DROPPED`.

So `dataset.quarantine_record` holds **only the rows that still need fixing**, one row per problem row.

**Strict keys:** a new row whose key is already loaded is never written over the loaded row.
- With the same values it is an `EXACT_DUPLICATE_ROW`, which is dropped.
- With different values it is quarantined as `DUPLICATE_PRIMARY_KEY` (`depends_on` = `<table>:<key>`).

Modules in `src/astra_etl/`:

| Module | Role |
|---|---|
| `clean.py` | Value cleaners. Decisions D1–D4, D6. |
| `spec.py` | Mapping per table (CSV column → cleaner → DB column), FKs, cross-column rules |
| `rules.py` | Quarantine rule catalog. Mirrors `dataset.quarantine_rule`. |
| `transform.py` | File discovery and validation, no database. Asserts both reconciliations (below). |
| `load.py` | Reads the state (registered files, quarantine, loaded keys). Writes one run in one transaction. |
| `fix.py` | `.\astra fix` commands: list / show / set / drop / history |

Both reconciliations are checked on every run:
- per new file: `read = loaded + quarantined + duplicate` (stored in `etl_run_file`);
- per table: `quarantine rows checked = graduated + still in quarantine + dropped as duplicate`
  (stored in `dq_check_result` as `quarantine_recheck`).

## Decision: strict quarantine (2026-11-17)

Products with a negative `list_price` (32) or a missing one (38) stay quarantined.
Every fact row that references them is quarantined too, with rule `ORPHAN_PARENT_QUARANTINED`.
That is 2,994 sales, 250 service orders, 421 procurement rows and 499 inventory rows.
They are not loaded with a NULL price.

## Every row is labelled

Each row in `dataset.quarantine_record` carries these labels:

- **`rule_id`**: one rule from `dataset.quarantine_rule`. The rule holds the description, the D-decision and the remediation.
- **`failed_columns`**: the column names to fix. Values are never stored here.
- **`depends_on`**: what the row waits for: `products:PRD00012`, or `row:<file>:<line>` of the row that was kept.
- **`raw_record`**: the source row, as edited. The ETL rechecks it every run. It may contain PII and is analyst-only.
- **`corrected_columns`**: the columns an analyst edited.
- **`source_file`**, **`source_row_number`**: where the row came from.

| rule_id | graduation_path | Meaning |
|---|---|---|
| REQUIRED_FIELD_MISSING | FIX_IN_QUARANTINE | Required value is blank, or a placeholder such as N/A or TBD |
| DATE_FORMAT_INVALID | FIX_IN_QUARANTINE | Date or time is not valid (D1) |
| NUMERIC_VALUE_INVALID | FIX_IN_QUARANTINE | Not a number, a word, or out of range (D3) |
| CATEGORY_VALUE_INVALID | FIX_IN_QUARANTINE | Value is outside the allowed set |
| NEGATIVE_AMOUNT | FIX_IN_QUARANTINE | Negative money amount (D4) |
| MANAGER_IS_SELF | FIX_IN_QUARANTINE | Employee is listed as their own manager |
| WAREHOUSE_CODE_FORMAT | FIX_IN_QUARANTINE | Code is not `WH-AAA-00` |
| CHECKOUT_BEFORE_CHECKIN | FIX_IN_QUARANTINE | Check-out time is earlier than check-in |
| DUPLICATE_PRIMARY_KEY | FIX_IN_QUARANTINE | Same key as a loaded row but different content (D5) |
| ORPHAN_PARENT_QUARANTINED | AUTO_WITH_PARENT | Parent row is itself in quarantine |
| ORPHAN_KEY_NOT_IN_SOURCE | FIX_IN_QUARANTINE | Parent key is not loaded and not in quarantine. Graduates by itself when a later file brings the parent. |
| EXACT_DUPLICATE_ROW | NOT_NEEDED | Identical copy of a loaded or held row. Never loaded; archived. |

## How a row graduates to valid data

Fix the value inside the quarantine row. The source files are never changed.

1. **Find** what to fix. `list` shows the quarantine id, table, key, rule, the columns to fix,
   what the row waits for, and the file and line. It shows no values.

   ```powershell
   .\astra fix list --table products
   ```

2. **Look** at one row: its rule, how to fix it, the current values and earlier edits.
   The failing columns are marked `<- fix`.
   The output can contain personal data, so use it on your own machine only.

   ```powershell
   .\astra fix show products PRD00012
   ```

3. **Fix** the value. Use the column name from the source CSV. `--reason` is required.

   ```powershell
   .\astra fix set products PRD00012 list_price 250000 --reason "price list 2024"
   ```

   - The old value is saved in `dataset.quarantine_edit`, with the new value, the reason, the user and the time.
   - `--blank` makes the cell empty instead of setting a value.
   - When several rows share a key (`DUPLICATE_PRIMARY_KEY`), add `--id N` with the id from `list` or `show`.
     For example, give the second row a new key:
     `.\astra fix set sales_transactions SAL00000004 transaction_id SAL00000009 --id 812 --reason "..."`.
   - To undo an edit, set the old value again (see `history`).
   - Put double quotes around any value that contains spaces, commas or `=`.
   - For `AUTO_WITH_PARENT` rows, fix the parent named in `depends_on`.
     All the rows waiting on that parent graduate in the same run.

4. **Remove** a row that should never load, for example a wrong duplicate of a loaded row:

   ```powershell
   .\astra fix drop 812 --reason "same sale as the loaded row"
   ```

   It is archived as `DROPPED` with your reason, and deleted from quarantine. Loaded data is not touched.

5. **Rerun** the ETL with `.\astra etl`.
   Fixed rows that pass are loaded and leave quarantine. The others stay, with their new rule if it changed.

6. **Track** progress:
   - `.\astra fix history` lists edits, newest first, and whether each row graduated.
   - The view `v_quarantine_lifecycle` counts rows per table and rule: `OPEN` (in quarantine) and
     `GRADUATED` / `DUPLICATE_DROPPED` / `DROPPED` / `SUPERSEDED` (archive).
   - The view `v_quarantine_open` counts rows in quarantine per rule.

**Access:**
- `astra_analyst` may delete rows from `quarantine_record` only, and always through the archive.
  Every other table stays insert/update only.
- `quarantine_archive`, `quarantine_edit` and `source_file` are append-only for `astra_analyst`.
- `astra_reporting` sees the archive and edit metadata (table, file, rule, columns, resolution, dates).
  It does not see keys, values, reasons or authors.
- The archive keeps labels only, not raw values. The edit log keeps the old and new values of each edited cell.

## History

**First load (2026-11-17)**

| | Rows |
|---|---:|
| Read | 435,200 |
| Loaded | 428,516 |
| Quarantined | 5,984 |
| Exact duplicates | 700 |

Open records by rule at that time: ORPHAN_PARENT_QUARANTINED 4,164; ORPHAN_KEY_NOT_IN_SOURCE 1,153;
NUMERIC_VALUE_INVALID 337; REQUIRED_FIELD_MISSING 251; NEGATIVE_AMOUNT 79.

**Correction overlay (0007, 2026-11-18).** Before 0008, fixes were stored in `dataset.quarantine_correction`
and every run re-read the CSVs and re-created the quarantine records (statuses OPEN / SUPERSEDED / GRADUATED /
DISMISSED). Fix #2 (`PRD00148 list_price`) graduated 70 rows that way.
Its 2 rows were copied to `quarantine_edit` in 0008. Migration 0009 (2026-11-18) dropped
`quarantine_correction` and its view `v_correction_status`. `.stra fix history` still shows those 2 edits as `legacy correction`.

**Migration 0008 (2026-11-18).** It kept the 5,914 OPEN rows as the live quarantine.
It moved the history (17,882 SUPERSEDED, 2,800 duplicates, 70 GRADUATED) to `quarantine_archive`
and registered the 10 loaded files in `source_file`.

**Checks after 0008 (2026-11-18):**
- Dry run and the first real run: 0 new files, 5,914 quarantine rows rechecked, 0 graduated (no edits yet). A run now takes about 6 s.
- End-to-end check in one transaction that was rolled back: `fix set` on one product with a negative price
  graduated that product and the 79 rows waiting on it (80 rows loaded, archived as GRADUATED, deleted from quarantine).
  The edit log kept the old value. `fix drop` archived a row as DROPPED. `DELETE` on `products` was denied.

## Known limits

- The archive grows by one row per graduated or dropped row. No retention policy yet.
- A new row whose key is already loaded is quarantined, even when it is a real update of master data
  (for example a new product price). Updating loaded rows needs its own flow, which does not exist yet.
- Business rows keep `etl_run_id` and `source_row_number`. When one run reads two files of a table, the line
  number alone does not say which file a row came from; `source_file` is stored for quarantine rows only.
- A row with a blank primary key has no key to type: use `-` as KEY with `--id N`,
  for example `.stra fix set customers - customer_id CUS000123 --id 77 --reason "..."`.
