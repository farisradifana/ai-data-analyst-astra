# 32 — Telegram alerts

The ETL sends Telegram alerts after each real load (`.\astra etl`). Code: `src/astra_etl/notify.py`.
Thresholds: `config/alert_policy.json`.

## Setup (H3)

Put these in `.env` (see [HUMAN-STEPS.md](HUMAN-STEPS.md), H3):

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather |
| `TELEGRAM_CHAT_ID` | Numeric chat id (groups start with `-100`), or `@channelname` |
| `TELEGRAM_MESSAGE_THREAD_ID` | Optional topic id |

- If the token or chat id is empty, alerts are off. Nothing is sent and no id is guessed.
- A value in the wrong format switches alerts off with a message. The run itself continues.

Then, from the project folder:

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

- `check` checks the format of the values. It uses no network.
- `check --online` asks Telegram whether the token works and the bot can see the chat. It sends no message.
- `preview` prints the alerts that the last run summary would send. It uses no network.
- `test` sends one test message to the configured chat.

## When alerts are sent

- After every real load: one `ETL_SUCCESS` message, plus any warnings.
- When a load fails: one `ETL_FAILED` message, and the error is raised as before.
- Dry runs never send alerts. `.\astra etl --no-notify` skips them for one load.
- An alert that cannot be sent is logged on the console. It never fails the ETL run.

| Category | Severity | When | Content |
|---|---|---|---|
| `ETL_SUCCESS` | INFO | Every load | Run id (first 8 characters), trigger, new files per table, rows read / loaded / quarantined / duplicate, quarantine rechecked / graduated / still to fix, top 3 open rules, duration |
| `QUARANTINE_SPIKE` | WARNING | New quarantined rows ≥ 500, or ≥ 5 % of the new rows read | Count, share, the 3 tables with the most |
| `STALE_SOURCE` | WARNING | A `--trigger SCHEDULED` run found no new file | Fixed text |
| `ETL_FAILED` | CRITICAL | The load raised an error | Stage (connect, lock, read state, read files, validate, load) and the error **type** only |
| `TEST` | — | `.\astra notify test` | Fixed text |

## What is never sent

- Record values, keys, names, emails or phone numbers.
- File names. A file name is chosen by whoever delivers the file, so only the count per table is sent.
- Error messages. A database error can quote a row, so `ETL_FAILED` sends only the error type.
  The full error stays on the console of the ETL machine.
- The bot token. It is removed from any error text, and the config object hides it.

Alerts are built from the counts-only run summary (`reports/etl/last_run_summary.json`).
The notifier never reads the database.

## Delivery

- Python standard library over HTTPS (`api.telegram.org`), so it needs no extra package.
- Plain text, without `parse_mode`, so no HTML or Markdown in the text is interpreted. At most 4,096 characters.
- At least 1.1 s between messages, and at most 18 per minute. Telegram allows about 20 per minute in a group.
- Retries: up to 4 attempts, with a 15 s timeout each.
  - Network errors and HTTP 5xx wait 1 s, then 2 s, then 4 s, plus jitter.
  - HTTP 429 waits Telegram's `retry_after`, capped at 60 s.
  - Other errors, such as 400 (bad chat id), 401 (bad token) or 403 (bot removed), are not retried.

## Tests

`tests/etl/test_notify.py` has 12 offline tests, with no network. They cover:
- the config rules;
- the token never appearing in errors;
- retries on 5xx, network errors and 429;
- no retry on 400;
- the attempt limit and the rate limit;
- counts-only content, with no file names;
- the spike and stale rules;
- the failure alert hiding the error message;
- `deliver` never raising;
- the ETL sending a failure alert and raising again, while dry runs and `--no-notify` send nothing.

The live test of each category waits for H3.
