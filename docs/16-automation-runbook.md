# 16 — Automation runbook

Last checked: 2026-11-18

All data in this project is synthetic. This page lists every scheduled job, how to run it by hand, how to fix quarantined rows, and how to back up and restore.
Run every command from the project folder, in PowerShell or cmd.

## Scheduled jobs

There is one scheduled job.

| Item | Value |
|---|---|
| Task Scheduler name | `Astra Daily ETL` |
| Time | Daily 08:30 WIB (PC time zone SE Asia Standard Time, UTC+7). First run 2026-11-19 |
| Account | Current Windows user, only while signed in, no admin rights, no stored password |
| Job script | `scripts/daily_etl.ps1` (runs `astra etl --trigger SCHEDULED`) |
| Registration script | `scripts/register_daily_task.ps1` |
| Missed run | Starts as soon as possible (`StartWhenAvailable`) |
| Overlap | Skipped while a run is active (`IgnoreNew`). The ETL also holds a database lock |
| Time limit | Job stops itself after 30 minutes (`-TimeoutMinutes`, 1 to 240). Task Scheduler stops it after 1 hour |
| Logs | `logs\etl\etl-<yyyyMMdd-HHmmss>.log`, newest 30 kept, counts only, not in Git |
| Summary | `reports/etl/last_run_summary.md` and `.json` |

The registration script defaults to 02:00. The registered task uses 08:30 because `.\astra schedule -At 08:30` was run (see [doc 33](33-daily-schedule.md)).
If you register again without `-At`, the time goes back to 02:00.

Other automatic jobs: none. Nothing else is scheduled. The n8n workflow is imported inactive and the Laya API is started by hand.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | The ETL finished |
| 1 | The ETL failed, or the job script hit an error. The ETL sends an `ETL_FAILED` alert |
| 124 | Timeout. The job stopped the process tree and sent a `JOB_TIMEOUT` alert (unless `-NoNotify`) |
| other | The exit code of the ETL process |

PostgreSQL rolls back an open transaction when the run is cut off, so a timed-out run leaves no half-loaded data.
Task Scheduler shows the code as "Last Run Result".

### Check the task

```powershell
.\astra schedule -Show
```

It prints the state, trigger time, last run, last result and next run.

### Change or remove the task

```powershell
.\astra schedule -At 08:30
```
```powershell
.\astra schedule -Unregister
```

### Alerts

The ETL sends `ETL_SUCCESS`, `STALE_SOURCE`, `QUARANTINE_SPIKE` and `ETL_FAILED`. The job script sends `JOB_TIMEOUT`. Alerts hold counts only. See [doc 32](32-telegram-alerts.md).
A day without a new file sends `STALE_SOURCE`.

## Manual runs

| Goal | Command |
|---|---|
| Validate only, no writes, no alerts | `.\astra etl --dry-run` |
| Validate without any database | `.\astra etl --dry-run --offline` |
| Real load, no alerts | `.\astra etl --no-notify` |
| Real load, with alerts | `.\astra etl` |
| Exactly what the schedule runs (log, time limit) | `.\astra daily` |
| Same, validate only | `.\astra daily -DryRun -NoNotify` |

```powershell
.\astra daily -DryRun -NoNotify
```

Only one load runs at a time. A second one stops with "another ETL run is in progress".
Details: [doc 31](31-etl-and-quarantine.md), [doc 33](33-daily-schedule.md).

## Fix quarantined rows

Rows that fail a rule wait in `dataset.quarantine_record`. You fix them in the database, not in the CSV files.

```powershell
.\astra fix list --table products
```
```powershell
.\astra fix show products PRD00012
```
```powershell
.\astra fix set products PRD00012 list_price 250000 --reason "price list 2024"
```
```powershell
.\astra fix drop 812 --reason "same sale as the loaded row"
```
```powershell
.\astra etl
```
```powershell
.\astra fix history
```

- `list` shows ids, rules and failed columns, no values. `show` shows values and can contain personal data.
- `set` saves the old value in `dataset.quarantine_edit`. `--reason` is required.
- `drop` archives a row that must never load.
- The next ETL run (scheduled or manual) loads the rows that now pass.
- The full lifecycle, rules and options (`--id`, `--blank`) are in [doc 31](31-etl-and-quarantine.md).

## Backup and restore

### What to back up

| Item | Where it lives | How to back it up | Git? |
|---|---|---|---|
| Database (schema `dataset`) | Supabase project | See "Database backup" below | Never |
| `.env` | Project folder | Password manager (secure note) | Never (gitignored) |
| `secrets\supabase-ca.crt` | Project folder | Password manager, or download again from Supabase (Settings, Database, SSL certificate) | Never (gitignored) |
| n8n encryption key, main n8n | `%USERPROFILE%\.n8n\config` | Password manager | Never |
| n8n encryption key, Astra n8n | `%USERPROFILE%\.n8n-astra\.n8n\config` | Password manager | Never |
| Source CSV files | `raw-data\` (first delivery and daily files in `raw-data\<table>\`) | Copy to another disk or a private store | Never (gitignored, synthetic records) |
| ETL reports | `reports\` | Reports under `reports/` are in Git. Logs in `logs\` are not and may be discarded | Reports yes, logs no |
| Code, docs, SQL, n8n spec | Git repository | `git push` to the GitHub backup repo | Yes |
| n8n credentials and workflow state | `%USERPROFILE%\.n8n-astra` | The workflow is rebuilt from code (`.\astra n8n build`). Credentials are recreated by hand. The key file above is needed only to read the old credential store | Never |

Losing an n8n key file makes the stored n8n credentials unreadable.
The Supabase free tier has no point-in-time recovery, so a dump or the dashboard backups are the only copy of the database state.

### Database backup

Two options. Pick one and check it works before you need it.

1. Supabase dashboard backups. Open the project in the dashboard and look at Database, Backups. Availability depends on your plan. Not checked for this project.
2. A `pg_dump` of schema `dataset` as `astra_analyst`.

`pg_dump` was NOT tested. The PostgreSQL client is not installed on this PC (STATUS, phase 1 inventory: no `psql`). Install the client tools first. The command below is an untested outline:

```powershell
pg_dump --host=<pooler_host> --port=5432 --username=astra_analyst.<project_ref> --dbname=postgres --schema=dataset --format=custom --file=astra-dataset.dump
```

- Not tested. `pg_dump` asks for the password. Use the `PGPASSWORD` environment variable only in your own shell, and never write it in a file.
- The role `astra_analyst` has SELECT on every table in `dataset`, so it can read the data. Check that the dump has all tables after the first real run.
- The pooler must be the Session pooler (port 5432), not port 6543.
- Keep the dump outside the repository. `*.dump`, `*.backup` and `*.sql.gz` are gitignored, but do not rely on that. The dump holds synthetic customer and employee records, including `raw_record` in quarantine.
- Never commit or upload a dump.

### Restore

Restore assumes a new or empty Supabase project, or one where schema `dataset` was lost.

1. Rebuild `.env` and `secrets\supabase-ca.crt` from your backups. Use the new host and project ref if the project changed.
2. Apply `sql/migrations/*.sql` in file-name order (10 files, see [doc 30](30-database-schema.md)). The owner approves this step. Migrations are idempotent. 0009 stops first if legacy rows are missing.
3. Set the two role passwords in the Supabase SQL editor (`ALTER ROLE ... PASSWORD`). Never put them in chat.
4. Check the connection.

```powershell
.\astra check-db
```

5. Choose how to refill the data:
   - Restore from a dump: this is the only way to keep `quarantine_edit` history, `quarantine_archive`, `etl_run` history and the rows loaded from fixed quarantine. The restore command was not tested.
   - Reload from raw files: put the original files back in `raw-data\` and run the ETL.

```powershell
.\astra etl
```

### Is the reload safe to repeat? (checked in `src/astra_etl/load.py`)

Yes for files, with limits.

- Each file is registered in `dataset.source_file` with its SHA-256. A registered file is skipped on later runs, so running the ETL twice on the same files loads nothing twice.
- A registered file that changed stops the run with an error. Never edit a loaded file.
- A strict key rule stops a loaded row from being overwritten.
- On an empty database nothing is registered, so every file loads again from scratch.

Limits of "reload from raw files":

- Edits made with `.\astra fix set` and rows dropped with `.\astra fix drop` are stored only in the database. After a reload from CSV they are gone, and those rows return to quarantine.
- Run ids, timestamps and `etl_run` history are new.
- It needs the exact original files, including the daily files in `raw-data\<table>\`.

Reload from raw files was not run in this session (no database access allowed).

### After a restore

- Run `.\astra n8n check-live` and compare the counts with `reports/etl/last_run_summary.md`.
- Check that the n8n credential `Astra reporting (read-only)` still connects.
- Run `.\astra schedule -Show`.

## Related

[doc 31](31-etl-and-quarantine.md), [doc 32](32-telegram-alerts.md), [doc 33](33-daily-schedule.md), [17 troubleshooting](17-troubleshooting.md), [20 maintenance](20-maintenance.md), [HUMAN-STEPS](HUMAN-STEPS.md).
