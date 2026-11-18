# 11 — Telegram alerting

Last checked: 2026-11-18

Summary of the alerting design. Setup steps, message content and delivery details are in [doc 32](32-telegram-alerts.md).
Code: `src/astra_etl/notify.py`. Thresholds: `config/alert_policy.json`. All data is SYNTHETIC.

## What it does

The ETL sends Telegram messages after a real load (`.\astra etl`). The scheduled job ([doc 33](33-daily-schedule.md))
sends one more alert when it stops a run at its time limit.
Messages carry **counts only**: no record values, file names, error messages or personal data.
Alerts are built from `reports/etl/last_run_summary.json`. The notifier never reads the database.

## Alert types

| Category | Severity | Sent when |
|---|---|---|
| `ETL_SUCCESS` | INFO | A real load finished |
| `QUARANTINE_SPIKE` | WARNING | New quarantined rows reach the row or percentage threshold |
| `STALE_SOURCE` | WARNING | A `SCHEDULED` run found no new source file (and the policy allows it) |
| `JOB_TIMEOUT` | CRITICAL | `scripts/daily_etl.ps1` stopped a run at its time limit |
| `ETL_FAILED` | CRITICAL | The load raised an error. Only the stage and the error type are sent |
| `TEST` | — | `.\astra notify test` (the test message is fixed text) |

## Thresholds (`config/alert_policy.json`)

| Key | Value | Meaning |
|---|---|---|
| `quarantine_new_rows_warn` | 500 | `QUARANTINE_SPIKE` when new quarantined rows are at least this many |
| `quarantine_new_pct_warn` | 5.0 | ...or at least this percent of the rows read |
| `stale_source_warn_on_scheduled` | true | Send `STALE_SOURCE` for a scheduled run with no new file |
| `top_rules` | 3 | Number of open quarantine rules listed in `ETL_SUCCESS` |

If the file is missing, the same values are used as defaults in code.

## Rate limiting and retry

- At least 1.1 s between messages and at most 18 per minute (Telegram allows about 20 per minute in a group).
- Up to 4 attempts, 15 s timeout each.
- Network errors and HTTP 5xx: exponential backoff. HTTP 429: wait Telegram's `retry_after`, capped at 60 s.
- Other errors (400, 401, 403) are not retried.
- Plain text only, at most 4,096 characters. The bot token is removed from error text and never printed.
- A send failure is logged on the console. It never fails the ETL run.

## Switches

- If `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` is empty, alerts are off.
- A value in the wrong format also switches alerts off, with a message.
- Dry runs never send alerts. `.\astra etl --no-notify` skips them for one load. `.\astra daily -NoNotify` does the same for the daily job.

## `.\astra notify` subcommands

```powershell
.\astra notify check
```
```powershell
.\astra notify check --online
```
```powershell
.\astra notify preview
```
```powershell
.\astra notify test
```
```powershell
.\astra notify timeout --minutes 30
```

| Subcommand | Network | Does |
|---|---|---|
| `check` | no | Checks the format of the Telegram values in `.env` |
| `check --online` | yes | Calls `getMe` and `getChat`. Sends no message |
| `preview` | no | Prints the alerts the last run summary would send. Needs a summary: run `.\astra etl --dry-run` first |
| `test` | yes | Sends one fixed test message to the configured chat |
| `timeout --minutes N` | yes | Sends a `JOB_TIMEOUT` alert (N is limited to 1–1440). The daily job calls it; you rarely run it by hand |

## Telegram commands

The bot has **no chat commands**. It only sends alerts. It does not read or answer messages.

A Telegram chat with the data assistant is **not built**. n8n's Telegram Trigger needs a public webhook URL,
and the Astra n8n listens on `127.0.0.1` only. A tunnel or a hosted n8n would be needed, which means exposing a port.
This waits for a user decision. See [doc 35](35-n8n-data-assistant.md), "Not in this phase", and [doc 13](13-n8n-ai-agent.md).

`TELEGRAM_ALLOWED_USER_IDS` appears in `.env.example` for that future chat. No code reads it today.

## Status

Live check 2026-11-18: `notify check --online` found the bot and a supergroup with topics. `notify test` was delivered.
The first `ETL_SUCCESS` from a real load is still to be confirmed (see [STATUS.md](STATUS.md), phase 7).
