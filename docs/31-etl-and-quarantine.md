# 31 — ETL and quarantine lifecycle

## Run

```bash
PYTHONPATH=src python -m astra_etl --dry-run   # validate only, no database writes
PYTHONPATH=src python -m astra_etl             # load as astra_analyst (verify-full SSL)
```

The run reads `raw-data/<table>.csv` and connects with `.env` (see doc 30 and `scripts/check_db_connection.py`).
It writes a counts-only summary to `reports/etl/last_run_summary.{json,md}`, which contains no record content.
A full load takes about 100 s.

Modules in `src/astra_etl/`:

| Module | Role |
|---|---|
| `clean.py` | Value cleaners. Decisions D1–D4, D6. |
| `spec.py` | Mapping per table (CSV column → cleaner → DB column), FKs, cross-column rules |
| `rules.py` | Quarantine rule catalog. Mirrors `dataset.quarantine_rule`. |
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

1. Find what to fix as `astra_analyst`: open records by `rule_id`, with `failed_columns`, `depends_on` and `raw_record`.
   Dashboards use `v_quarantine_open`, which has no record content.
2. Fix the value in `raw-data/<table>.csv`.
   For `AUTO_WITH_PARENT`, fix the parent named in `depends_on`.
   Its children graduate in the same run.
3. Rerun `python -m astra_etl`. The earlier OPEN records of each table change status:
   - `GRADUATED`: the key is now loaded into the valid table.
   - `SUPERSEDED`: the key still fails. A new OPEN record, possibly under a different rule, replaces it.
   - `DISMISSED`: the row is no longer in the source file.

   `resolved_run_id` records which run made the change.
4. Track progress in `v_quarantine_lifecycle`, which counts records per table, rule and status.

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
- The GRADUATED transition is covered by the update logic.
  It has not yet been exercised by a real source fix.
