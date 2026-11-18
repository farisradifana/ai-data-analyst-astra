# 33 — Daily ETL job (Windows Task Scheduler)

The daily job runs the ETL once a day with `--trigger SCHEDULED`.
- Job script: `scripts/daily_etl.ps1`.
- Task Scheduler entry: `scripts/register_daily_task.ps1`.

Run both through the launcher, from the project folder, in PowerShell or cmd.

## Run the job by hand

```powershell
.\astra daily -DryRun -NoNotify
```
```powershell
.\astra daily
```

- The first command validates only. It writes nothing and sends no alert.
- The second is exactly what the schedule runs: a real load, then Telegram alerts.
  A day without a new file also sends `STALE_SOURCE`.

What the job does:

- It runs `.\astra etl --trigger SCHEDULED` from the project folder.
- It writes the console output to `logs\etl\etl-<yyyyMMdd-HHmmss>.log` and keeps the newest 30 logs.
  The output holds counts only. `logs/` is not in Git.
- It stops the run after 30 minutes (`-TimeoutMinutes`, 1–240).
  - It stops the whole process tree, because `astra.cmd` starts python as a child.
  - It sends a `JOB_TIMEOUT` alert, unless `-NoNotify` is set.
  - PostgreSQL rolls back the open transaction, so nothing from that run stays.
- Its exit code is the ETL's exit code, or 124 on a timeout. Task Scheduler shows it as "Last Run Result".

## The schedule (H6)

```powershell
.\astra schedule -Show
```
```powershell
.\astra schedule -At 02:00
```
```powershell
.\astra schedule -Unregister
```

- `-Show` prints the state, the last run, its result and the next run.
- `-At HH:MM` creates the task "Astra Daily ETL", or replaces it with the new time.
- `-Unregister` removes the task.

Task settings:

| Setting | Value | Why |
|---|---|---|
| Account | Current user, only while signed in, no admin rights | No password is stored |
| Trigger | Daily at `-At` (default 02:00) | |
| Missed run | Starts as soon as possible (`StartWhenAvailable`) | The PC may be off or asleep at 02:00 |
| Overlap | A new run is skipped while one is running (`IgnoreNew`) | The ETL also holds a database lock |
| Time limit | 1 hour in Task Scheduler. The job stops itself after 30 min | |
| Power | Runs on battery. Does not wake the PC | |

Limit: the task does not run while you are signed out.
Running it signed out needs "Run whether user is logged on or not", which stores your Windows password in Task Scheduler.

## Checks (2026-11-18)

- `.\astra daily -DryRun -NoNotify` → exit 0. The log has the per-table counts.
- `.\astra daily -DryRun -NoNotify -TimeoutSecondsOverride 2` → stopped after 2 s, exit 124.
  No ETL python process was left running.
- H6 (2026-11-18): `.\astra schedule -At 08:30` → registered.
  - The user chose 08:30 WIB. The PC time zone is SE Asia Standard Time, UTC+7.
  - `-Show` → state Ready, next run 2026-11-19 08:30.
  - Settings checked: StartWhenAvailable, IgnoreNew, 1 h limit, RunLevel Limited, Interactive logon.
- Launcher fix: `astra.cmd` used to return exit code 0 even when a command failed.
  The cause was `exit /b %ERRORLEVEL%` inside a `( )` block, which is expanded before the command runs.
  Each command now runs under its own label.
  Checked: a missing test file returns 4, passing tests return 0, an unknown command returns 2.
