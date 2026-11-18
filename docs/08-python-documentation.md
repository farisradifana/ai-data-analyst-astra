# 08 — Python and script documentation

Last checked: 2026-11-18

This page lists every Python module and script under `src/` and `scripts/`, plus the launcher `astra.cmd`.
Run commands from the project folder, in PowerShell or cmd. `astra.cmd` sets `PYTHONPATH` to `src`.
The ETL, notify, n8n and `check-db` commands use the system `python`. The `test` and Laya commands use `.venv-laya`.

## Launcher: `astra.cmd`

| Command | Runs |
|---|---|
| `.\astra etl [flags]` | `python -m astra_etl etl ...` |
| `.\astra fix <sub> ...` | `python -m astra_etl fix ...` |
| `.\astra notify <sub> ...` | `python -m astra_etl notify ...` |
| `.\astra n8n build\|lint\|check-live` | `python -m astra_n8n ...` |
| `.\astra n8n-start` | Starts n8n at `http://astra.localhost:5698` (loopback only, own data folder, Supabase CA trusted). Extra arguments go to `n8n start` |
| `.\astra daily [-DryRun] [-NoNotify]` | `scripts\daily_etl.ps1` |
| `.\astra schedule [-Show\|-Unregister\|-At HH:MM]` | `scripts\register_daily_task.ps1` |
| `.\astra check-db` | `python scripts\check_db_connection.py` |
| `.\astra test [args]` | `.venv-laya\Scripts\python.exe -m pytest -q` |
| `.\astra laya-test [args]` | pytest with `-m laya`, `HF_HUB_OFFLINE=1` |
| `.\astra laya-api` | `python -m decision_engine.api` in `.venv-laya`, `HF_HUB_OFFLINE=1` |
| `.\astra laya-eval [args]` | `python -m decision_engine.evaluation` in `.venv-laya` |

The launcher returns the exit code of the command it runs. With no command, or an unknown one, it prints the usage and returns 2.
Running `.\astra` with no command never starts a load.

## Package `astra_etl` (`src/astra_etl/`)

Entry point: `python -m astra_etl` (file `__main__.py`). Workflow: [doc 07](07-etl-workflow.md). Rules: [doc 06](06-data-quality-rules.md).

| Module | Purpose | Key names | Inputs and outputs |
|---|---|---|---|
| `__init__.py` | Package docstring only | none | none |
| `__main__.py` | CLI and run control. Dispatches `fix` and `notify` to their modules, otherwise runs the ETL | `main`, `_run`, `write_summary`, `_table_summary`, `_git_version`, `_Stage` | Reads `raw-data/`, the database and `config/alert_policy.json`. Writes `reports/etl/last_run_summary.json` and `.md`. Exit 0 on success; an exception gives a non-zero exit |
| `db.py` | Database connection from `.env` | `ROOT`, `load_env`, `connect(role)` | `connect("analyst")` uses `DATABASE_USER`, `connect("reporting")` uses `REPORTING_DB_USER`. User name is `<user>.<project_ref>`. Needs a 20 character `SUPABASE_PROJECT_REF`. Default SSL mode `verify-full` with the CA file from `DATABASE_SSLROOTCERT` (default `secrets/supabase-ca.crt`) |
| `clean.py` | Pure value cleaners. Each returns a canonical value or raises `CleanError(code)` | `CleanError`, `required`, `optional`, `code`, `name`, `identifier`, `date`, `time`, `money`, `integer`, `percent`, `flag`, `payment_terms`, `email`, `phone`, `is_blank`, `SENTINELS` | Raw string in, clean value out. No I/O |
| `spec.py` | Per-table mapping: CSV column, cleaner, database column, foreign keys, row rules | `Column`, `TableSpec`, `SPECS` (load order), `SPEC_BY_NAME`, `BRANCHES`, `DEPARTMENTS` | No I/O. `products.is_active` reads the source column `active_flag` |
| `rules.py` | Quarantine rule catalog (12 rules) | `Rule`, `RULES`, `COLUMN_RULE` | No I/O. Mirrors `dataset.quarantine_rule` |
| `transform.py` | File discovery, reading, validation and reconciliation. No database access | `discover`, `read_source`, `read_csv`, `sha256_file`, `clean_table`, `apply_foreign_keys`, `transform`, `transform_dir`, dataclasses `SourceFile`, `OpenRecord`, `Quarantined`, `Loaded`, `FileStats`, `TableResult` | In: file paths, open quarantine rows, loaded keys. Out: a `TableResult` per table. Asserts both reconciliations |
| `load.py` | Database side: read state, write one run | `lock`, `read_state`, `existing_rows`, `new_files`, `load`, `_insert_rows`, `_quarantine`, `_leave_quarantine`, `_audit` | Reads `source_file`, `quarantine_record` and primary keys. Writes business tables, `etl_run`, `etl_run_file`, `source_file`, `dq_check_result`, `quarantine_record`, `quarantine_archive`. `load(..., commit=False)` leaves the transaction open |
| `fix.py` | Edit rows in quarantine | `main`, `_run`, `_print_history` | Reads and writes `quarantine_record`, `quarantine_edit`, `quarantine_archive` as `astra_analyst`. Exit 0 ok, 2 for a usage or not-found error |
| `notify.py` | Telegram alerts and their CLI | `Telegram`, `TelegramConfig`, `Alert`, `run_alerts`, `failure_alert`, `timeout_alert`, `deliver`, `client_from_env`, `config_from_env`, `load_policy`, `main` | Reads `.env` (names `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_MESSAGE_THREAD_ID`), `config/alert_policy.json` and the run summary. Calls the Telegram Bot API. The token is never printed |

### CLI: `astra etl`

`python -m astra_etl [etl] [flags]`. Usage text in the code: `astra etl [--dry-run] [--offline] [--trigger MANUAL|SCHEDULED|REPROCESS] [--no-notify]`.

| Flag | Meaning |
|---|---|
| `--dry-run` | Validate only. No database writes, no alerts |
| `--offline` | With `--dry-run` only. No database; every file is treated as new. Without `--dry-run` it is refused |
| `--trigger` | `MANUAL` (default), `SCHEDULED` or `REPROCESS`. Stored in `etl_run.trigger_type` and shown in alerts |
| `--no-notify` | Do not send Telegram alerts for this load |

### CLI: `astra fix`

`python -m astra_etl fix <subcommand>`. `--table` accepts the ten table names. Output of `show` and `history` can contain personal data.

| Subcommand | Arguments and flags | Effect |
|---|---|---|
| `list` | `--table T`, `--rule R`, `--limit N` (default 50, capped at 1000) | Lists quarantine rows: id, table, key, rule, columns to fix, `waits_for`, file and line. No values |
| `show` | `TABLE KEY` | Rule, how to fix, current values (failing columns marked `<- fix`) and the last 20 edits |
| `set` | `TABLE KEY COLUMN [VALUE]`, `--reason TEXT` (required, 3 to 300 characters), `--id N`, `--blank` | Changes one cell in the quarantine row and logs the old value in `quarantine_edit`. Give a `VALUE` or `--blank`, not both. `COLUMN` is a source CSV column. Value up to 500 characters. If several rows share the key, repeat with `--id N` |
| `drop` | `QUARANTINE_ID`, `--reason TEXT` (required) | Archives the row as `DROPPED` and deletes it from quarantine. Loaded data is not touched |
| `history` | `--table T`, `--key K`, `--limit N` (default 50, capped at 1000) | Edits, newest first, with the state of each row |

### CLI: `astra notify`

`python -m astra_etl notify <subcommand>`. Details: [doc 32](32-telegram-alerts.md).

| Subcommand | Flags | Effect |
|---|---|---|
| `check` | `--online` | Checks the `.env` format (no network). With `--online` it calls `getMe` and `getChat`; no message is sent |
| `preview` | none | Prints the alerts the last run summary would send. No network |
| `test` | none | Sends one test message to the configured chat |
| `timeout` | `--minutes N` (required, 1 to 1440) | Sends the `JOB_TIMEOUT` alert. Used by `scripts/daily_etl.ps1` |

## Package `astra_n8n` (`src/astra_n8n/`)

The n8n data assistant. Design and tools: [doc 35](35-n8n-data-assistant.md).

| Module | Purpose | Key names | Inputs and outputs |
|---|---|---|---|
| `__init__.py` | Package docstring only | none | none |
| `assistant.py` | Defines the assistant: nine read-only SQL tools, the system message and the n8n workflow JSON | `TOOLS`, `Tool`, `Param`, `build_workflow`, `write_workflow`, `tool_node`, `model_name`, `placeholders`, `to_psycopg`, `WORKFLOW_NAME` | Out: workflow JSON. Each tool is one `SELECT` on a `dataset.v_*` view; values reach the database only as `$n` parameters |
| `__main__.py` | CLI `build`, `lint`, `check-live` | `cmd_build`, `cmd_lint`, `cmd_check_live`, `lint_tool`, `REFERENCE_2025`, `SAMPLE` | See below |

Tools in `TOOLS`: `get_sales_kpis`, `get_sales_breakdown`, `get_sales_monthly`, `get_service_kpis`, `get_procurement_inventory`, `get_expense_summary`, `get_attendance_kpis`, `get_customer_activity`, `get_data_quality_status`.

| Subcommand | Flags | Effect |
|---|---|---|
| `build` | `--out PATH` (default `n8n/build/astra_data_assistant.json`) | Lints every tool, then writes the workflow JSON. The model comes from `LLM_MODEL` in `.env`; if empty the node says `SET_LLM_MODEL`. Exit 1 if lint fails, 2 for an invalid model name |
| `lint` | none | Static checks per tool: starts with `SELECT`/`WITH`, no `;`, no comments, no write keywords, reads only `dataset.v_*` views, placeholders match parameters, name starts with `get_`. Offline. Exit 1 if any tool fails |
| `check-live` | none | Runs every tool as `astra_reporting` in a `READ ONLY` transaction and compares some results with 2025 reference values. Also confirms the role cannot `INSERT`. Needs the database. Exit 1 on a mismatch |

## Package `decision_engine` (`src/decision_engine/`)

Laya, the local decision engine. It only classifies into closed label sets. Docs: [22](22-laya-architecture.md) to [29](29-laya-cost-and-resource-usage.md).

| Module | Purpose | Key names | Inputs and outputs |
|---|---|---|---|
| `__init__.py` | Package docstring | none | none |
| `decision_schemas.py` | Closed label sets and request/response models | `DQCategory`, `RouteCategory`, `DQ_CRITERIA`, `ROUTE_CRITERIA`, `PredictRequest`, `Decision`, `TaskName` (`dq_category`, `agent_route`) | Text up to 2,000 characters in; a `Decision` out |
| `model_manager.py` | Loads the Laya router once, CPU only | `ModelManager`, `CHECKPOINTS` (`multilingual`, `english`, `typed-decisions`) | Env: `LAYA_CHECKPOINT` (default `multilingual`), `LAYA_THREADS` (default 4). `HF_HUB_OFFLINE=1` forbids network use |
| `confidence_policy.py` | Confidence bands and actions | `TaskPolicy`, `load_policy` | Reads `config/laya_policy.json`. High band gives `ACCEPT` (if the task is enabled), medium gives `REVIEW`, low gives `FALLBACK`. Without the file every task is disabled |
| `fallback.py` | Keyword rules used when Laya fails or is not confident | `classify`, `classify_dq`, `classify_route` | Text in, label out. Returns `UNKNOWN_ERROR` or `UNKNOWN` rather than guessing |
| `laya_engine.py` | Prediction, then policy, then decision, with fallback | `DecisionEngine.decide`, `laya_choice` | `PredictRequest` in, `Decision` out. Never runs SQL or sends messages. Logs do not contain the input text |
| `api.py` | Local HTTP API (FastAPI) | `create_app`, `main` | Binds `127.0.0.1:8765` by default (`LAYA_API_HOST`, `LAYA_API_PORT`). Refuses a non-loopback host unless `LAYA_API_ALLOW_REMOTE=1`. Needs `LAYA_API_TOKEN` of 16 characters or more |
| `evaluation.py` | Benchmarks the checkpoints on the labeled synthetic sets | `run`, `metrics`, `write_md`, `main` | Reads `evals/laya/*.jsonl`. Writes `reports/laya/`. Does not change `config/laya_policy.json` |

### Laya API endpoints

| Method and path | Auth | Purpose |
|---|---|---|
| `GET /health` | none | `ready`, `loading` or `error` |
| `GET /model-info` | Bearer token | Checkpoint, pinned revision and task policy |
| `POST /predict` | Bearer token | Body is a `PredictRequest`; returns a `Decision` |
| `POST /evaluate` | Bearer token | Up to 50 labeled items; returns accuracy and per-item results |

Request bodies are capped at 64 KB. One inference runs at a time, with a timeout (`LAYA_API_TIMEOUT_S`, default 30).

### CLI: `astra laya-eval`

`python -m decision_engine.evaluation`. Arguments are passed through the launcher.

| Flag | Default | Meaning |
|---|---|---|
| `--checkpoints NAME [NAME ...]` | `multilingual english typed-decisions` | Checkpoints to benchmark |
| `--threads N` | 4 | CPU threads |

## Scripts (`scripts/`)

| File | Purpose | Entry point | Inputs and outputs |
|---|---|---|---|
| `check_db_connection.py` | Checks `.env` completeness and that both roles can log in | `.\astra check-db` | Prints variable names with filled or empty status, then one line per role. Never prints values, hosts or the project ref. Exit 0 if both connect with the configured SSL mode, else 1 |
| `profile_raw.py` | Read-only profiler for the raw CSV files (phase 1) | `python scripts\profile_raw.py` (no launcher command) | Flags: `--raw-dir` (default `raw-data`), `--out` (default `reports/profiling`). Writes `source_inventory.csv`, `profile_<table>.json`, `fk_checks.json` and `profiling_summary.md`. Needs `pandas`. Exit 2 if no data files are found |
| `daily_etl.ps1` | Scheduled job: runs `astra etl --trigger SCHEDULED` with a time limit and a log | `.\astra daily` | See below |
| `register_daily_task.ps1` | Creates, shows or removes the Task Scheduler entry "Astra Daily ETL" | `.\astra schedule` | See below |

### `daily_etl.ps1` parameters

Details: [doc 33](33-daily-schedule.md).

| Parameter | Default | Meaning |
|---|---|---|
| `-TimeoutMinutes` | 30 (range 1 to 240) | Stops the run after this time and sends `JOB_TIMEOUT` |
| `-TimeoutSecondsOverride` | 0 (range 0 to 3600) | For tests only |
| `-KeepLogs` | 30 (range 1 to 365) | Number of logs kept in `logs\etl` |
| `-DryRun` | off | Adds `--dry-run` |
| `-NoNotify` | off | Adds `--no-notify` and skips the timeout alert |

Output: `logs\etl\etl-<yyyyMMdd-HHmmss>.log`. Exit code is the ETL's exit code, or 124 on timeout.

### `register_daily_task.ps1` parameters

| Parameter | Default | Meaning |
|---|---|---|
| `-At HH:MM` | `02:00` | Creates or replaces the daily task at this time |
| `-Show` | off | Prints state, last run, last result and next run |
| `-Unregister` | off | Removes the task |

## Tests

`tests/etl/` (clean, rules, transform, requeue, notify), `tests/n8n/test_assistant.py` and `tests/decision_engine/` run with `.\astra test`.
Tests marked `laya` need the real model: `.\astra laya-test`.
SQL privilege tests are in `sql/tests/` ([doc 10](10-sql-reference.md)).
