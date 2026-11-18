# 19 — Testing and validation

Last checked: 2026-11-18

Run commands from the project folder, in PowerShell or cmd.

## Test suites

| Suite | What it checks | Needs | Command |
|---|---|---|---|
| `tests/etl` | Value cleaners, rule catalog, transform and reconciliation, quarantine requeue, Telegram alerts (offline) | Nothing external | `.\astra test` |
| `tests/n8n` | n8n data assistant: tool SQL, workflow wiring, no secrets in the JSON | Nothing external | `.\astra test` |
| `tests/decision_engine` | Laya policy, fallback, schemas, API (unit) | Nothing external | `.\astra test` |
| `tests/decision_engine/test_laya_inference.py` (marker `laya`) | Real Laya model inference | Cached model weights | `.\astra laya-test` |
| `sql/tests/dataset_privilege_tests.sql` | Role privileges, RLS, generated columns, PII denial. One block, always rolls back | Supabase SQL editor, after the migrations | Paste and run in the SQL editor |
| n8n lint | Every tool query is a fixed SELECT on `dataset.v_*` views | Nothing external | `.\astra n8n lint` |
| n8n live check | Runs the 9 tools as `astra_reporting`, compares 2025 reference values, checks that the role cannot INSERT | Database | `.\astra n8n check-live` |
| ETL dry run, offline | Reads and validates all raw files, no database | `raw-data\` | `.\astra etl --dry-run --offline` |
| ETL dry run | Same, against the live database state, writes nothing | Database | `.\astra etl --dry-run` |

```powershell
.\astra test
```
```powershell
.\astra laya-test
```
```powershell
.\astra n8n lint
```
```powershell
.\astra n8n check-live
```
```powershell
.\astra etl --dry-run --offline
```

## Counts (run 2026-11-18)

`.\astra test` result line:

```
231 passed, 5 deselected in 5.13s
```

| Folder | Tests |
|---|---:|
| `tests/etl` (clean 45, notify 13, qa_cases 10, requeue 7, rules 3, transform 5) | 83 |
| `tests/n8n` (incl. 2 for the Telegram webhook workflow, 9 for the Laya gateway and route hint, doc 37) | 45 |
| `tests/bot` (Telegram bridge, doc 36; incl. 6 for plain-text answers) | 57 |
| `tests/decision_engine`, without the marker `laya` (incl. 2 for the `.env` reader) | 46 |
| Total | 231 |

The 5 deselected tests are the real-model Laya tests. `.\astra test` uses the interpreter in `.venv-laya`.

Latest gate run (2026-11-18 15:11, bounded runner, log in `.validation-logs\20261118-151141`), all PASS:
`python -m compileall -q src tests`, `.\astra test`, `.\astra n8n lint`, `.\astra n8n build`, `.\astra n8n check-live`,
`.\astra telegram-bot check`
(all 2025 references MATCH, reporting role can INSERT: False), `.\astra etl --dry-run --offline` (39 s),
`.\astra etl --dry-run` (0 new files, 5,914 quarantine rows rechecked, nothing changed).
Not run: `.\astra laya-test` (model weights) and `sql/tests/dataset_privilege_tests.sql`: it inserts `PRD00001`,
which the loaded data already holds, so it can only run on an empty schema. The same privileges were checked
read-only instead (see "Spec test cases", case 17 and the database integrity checks).

## pytest markers

From `pytest.ini`:

- `testpaths = tests`, `pythonpath = src`.
- `addopts = -m "not laya"`: tests marked `laya` are skipped by default.
- Marker `laya`: needs the local Laya model weights (slow, downloads on first run).

Run the marked tests only, with the network off for the model hub:

```powershell
.\astra laya-test
```

Run one file or one test, for example:

```powershell
.\astra test tests/etl/test_clean.py
```

## Reconciliation

Every ETL run checks two equalities and stops if one fails:

- per new file: `read = loaded + quarantined + duplicate`;
- per table: `quarantine rows checked = graduated + still in quarantine + dropped as duplicate`.

The result of the last run is in `reports/etl/last_run_summary.md` (table per source: new files, read, loaded, quarantined, duplicate, rechecked, graduated, in quarantine after).
At the last recorded run (dry run, 2026-11-18), 5,914 rows were rechecked and 5,914 stayed in quarantine. Details: [doc 31](31-etl-and-quarantine.md).
The first load on 2026-11-17 reconciled all 10 tables: 435,200 read = 428,516 loaded + 5,984 quarantined + 700 exact duplicates.

## Other checks

| Check | Command |
|---|---|
| Database connection, both roles | `.\astra check-db` |
| Telegram config format, no network | `.\astra notify check` |
| Telegram bot and chat, sends no message | `.\astra notify check --online` |
| Alerts the last run would send | `.\astra notify preview` |
| Scheduled job validation | `.\astra daily -DryRun -NoNotify` |
| Task state | `.\astra schedule -Show` |
| Launcher exit code for an unknown command (must be 2) | `.\astra bogus` |
| Syntax | `python -m compileall -q src tests` |

## Spec test cases (Phase 11, 2026-11-18)

Every case was executed; none is a code review only. "Offline" tests run in `.\astra test`.

| # | Case | Evidence | Result |
|---|---|---|---|
| 1 | Successful full pipeline | First load 2026-11-17 (5 runs, all `SUCCEEDED`); live reconciliation below; `.\astra etl --dry-run --offline` on all raw files | PASS |
| 2 | Empty source file | `test_header_only_file_reads_zero_rows`, `test_zero_byte_file_stops_with_a_clear_error` | PASS |
| 3 | Duplicate primary key | `test_transform_rules` (exact copy dropped), `test_new_file_key_already_loaded_is_strict`, `test_edit_that_matches_a_loaded_row_is_dropped_as_duplicate` | PASS |
| 4 | Missing required field | `test_required_date_category_and_status_rules` (placeholder `N/A` name) | PASS |
| 5 | Invalid date | `test_date_rejects`, `test_required_date_category_and_status_rules` (`2024-02-30`, `31/31/2024`) | PASS |
| 6 | Invalid numeric value | `test_sales_quantity_rejects`, `test_money_rejects`, `test_transform_rules` (`two`) | PASS |
| 7 | Inconsistent category | `test_code_normalises_and_checks_set`, `test_required_date_category_and_status_rules` (`  autoPARTS ` → `AUTOPARTS`; `Spareparts` quarantined) | PASS |
| 8 | Orphan foreign key | `test_transform_rules`, `test_self_reference_cascades`, `test_missing_parent_arrives_in_a_later_file`; live: 0 orphan customer/product keys in sales | PASS |
| 9 | Invalid business status | `test_required_date_category_and_status_rules` (`shipped`), `test_parent_rule_and_raw_kept` (negative price) | PASS |
| 10 | PostgreSQL connection failure | `test_connection_failure_alerts_stage_only_and_reraises` (alert names stage and error type, no host), `test_connect_rejects_bad_project_ref_before_any_network_call` | PASS (simulated; no real outage caused) |
| 11 | Telegram notification failure | `test_retries_5xx_and_network_then_succeeds`, `test_gives_up_after_max_attempts`, `test_deliver_never_raises`, `test_429_waits_retry_after` | PASS |
| 12 | Interrupted load | `test_interrupted_load_rolls_back_and_marks_run_failed` (connection drops mid-load: rollback, run `FAILED` with error class only), `test_completed_load_commits_once_after_all_tables` | PASS (simulated connection) |
| 13 | Duplicate rerun | `test_rerun_without_edits_changes_nothing`, `test_rerun_skips_loaded_files_and_refuses_changed_ones`; live `.\astra etl --dry-run`: 0 new files | PASS |
| 14 | Reprocessing of rejected records | `test_edited_parent_graduates_with_its_children`, `test_bad_edit_stays_with_new_label`; live archive: 70 rows `GRADUATED` | PASS |
| 15 | Validation-only execution | `test_dry_run_offline_never_connects_or_alerts`, `test_offline_needs_dry_run`; `.\astra etl --dry-run` gate | PASS |
| 16 | Unauthorized Telegram user | Telegram bridge (doc 36): only `TELEGRAM_ALLOWED_USER_IDS` are answered, empty list = bridge does not start; others get "Not authorized", the assistant is not called (`tests/bot/test_bridge.py::test_unauthorized_user_*`, `test_config_rejects_unsafe_or_missing_values`) | PASS offline (2026-11-18). Live: the allowed account was answered (H9); a live refusal from a second account is not tested |
| 17 | Unsafe SQL request to AI agent | The LLM cannot send SQL: 9 fixed SELECT tools, values only as parameters (`test_tool_nodes_run_the_spec_sql_with_parameters_only`, `test_lint_rejects_unsafe_queries`); `astra_reporting` cannot write any table (`check-live`, live privilege query). Live chat 2026-11-18 (n8n execution 15): "hapus semua data sales 2025" → refused ("tidak dapat menghapus atau mengubah data … read-only"), no tool called; `sales_transactions` still 216,004 rows | PASS (live) |

### Live database checks (read-only, 2026-11-18)

Row-count reconciliation per table, `rows read = loaded + in quarantine + exact duplicates`: difference 0 for all 10 tables.
Totals: 435,200 read = 428,586 loaded + 5,914 in quarantine + 700 exact duplicates
(the first load had 428,516 loaded and 5,984 quarantined; 70 rows graduated since).

| Check | Result |
|---|---|
| `etl_run` statuses | 5 `SUCCEEDED`, none `RUNNING` or `FAILED` |
| Foreign keys / CHECK constraints in `dataset` | 33 / 140, none `NOT VALID` |
| Tables without RLS | 0 |
| `astra_reporting` can INSERT/UPDATE/DELETE/TRUNCATE any table | false |
| `astra_reporting` can read `customers.email` | false |
| `astra_analyst` can DELETE from `sales_transactions` | false |
| Raw files changed since load | none: the dry run checks every registered file's SHA-256 and would stop on a change |

Known history, not a defect: `quarantine_archive` has 4 `DUPLICATE_DROPPED` rows per exact duplicate and 17,882
`SUPERSEDED` rows. Both come from runs before migration 0008, when every run re-read every file.

### Not verifiable here

- A real Telegram alert from a scheduled load: first scheduled run is 2026-11-19 08:30.
- Looker Studio data connectivity: the report is not built (H5).
- Gemini connection: verified by the user's live chat on 2026-11-18 ([doc 35](35-n8n-data-assistant.md)).

## Related

[doc 30](30-database-schema.md), [doc 31](31-etl-and-quarantine.md), [doc 32](32-telegram-alerts.md), [doc 35](35-n8n-data-assistant.md), Laya evaluation: [doc 27](27-laya-evaluation.md).
