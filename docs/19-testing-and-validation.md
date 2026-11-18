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
151 passed, 5 deselected in 5.76s
```

| Folder | Tests |
|---|---:|
| `tests/etl` (clean 45, notify 13, requeue 7, rules 3, transform 5) | 73 |
| `tests/n8n` | 34 |
| `tests/decision_engine`, without the marker `laya` | 44 |
| Total | 151 |

The 5 deselected tests are the real-model Laya tests. `.\astra test` uses the interpreter in `.venv-laya`.

`.\astra n8n lint` was run in this session. Its output ended with OK for each tool, including `get_data_quality_status`. Earlier result, 9 of 9 OK ([doc 35](35-n8n-data-assistant.md)).

Not run in this session: `.\astra n8n check-live`, `.\astra etl --dry-run`, `.\astra laya-test` and the SQL privilege tests. They need the database, the weights or the SQL editor. The last recorded results are in [doc 35](35-n8n-data-assistant.md), [doc 30](30-database-schema.md) and [doc 23](23-laya-installation.md) (the privilege block passed 13 of 13 checks).
`.\astra etl --dry-run --offline` was also not run, because it rewrites `reports/etl/last_run_summary.md`.

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
At the last recorded run, 5,914 rows were rechecked and 5,914 stayed in quarantine. Details: [doc 31](31-etl-and-quarantine.md).
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

## Not done yet

The 17 test cases of the specification (Phase 11) are not done. The final review and the final report are not done either. See [STATUS](STATUS.md).

## Related

[doc 30](30-database-schema.md), [doc 31](31-etl-and-quarantine.md), [doc 32](32-telegram-alerts.md), [doc 35](35-n8n-data-assistant.md), Laya evaluation: [doc 27](27-laya-evaluation.md).
