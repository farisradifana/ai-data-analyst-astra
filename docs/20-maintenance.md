# 20 — Maintenance

Last checked: 2026-11-18

Routine tasks and how to do them. Run commands from the project folder, in PowerShell or cmd.

## Routine

| When | Task | How |
|---|---|---|
| Daily | Check that the scheduled run worked | Telegram `ETL_SUCCESS` message, or the newest file in `logs\etl`. Task state: `.\astra schedule -Show` (last result must be 0) |
| Weekly | Keep the Supabase free-tier project active (it pauses after about 7 days idle) | The daily ETL already counts as activity. Open the dashboard if the PC was off for days |
| Weekly | Review quarantine | `.\astra fix list`, the views `v_quarantine_open` and `v_quarantine_monitor`, then fix or drop rows ([doc 16](16-automation-runbook.md)) |
| After a change | Run the unit tests | `.\astra test` |
| Monthly | Back up what is not in Git | See "Backup and restore" in [doc 16](16-automation-runbook.md) |
| After new files arrive | Put each file in `raw-data\<table>\`, named by date. The next run loads it | [doc 31](31-etl-and-quarantine.md) |

```powershell
.\astra schedule -Show
```
```powershell
.\astra fix list
```
```powershell
.\astra fix history
```

Logs in `logs\etl` hold counts only. The job keeps the newest 30.

## Database migrations

- A change to the schema is a new file in `sql/migrations/`, named `<yyyyMMddHHmmss>_<name>.sql`, later than all existing ones.
- Never edit a migration that was applied. Add a new one.
- Keep it idempotent (`IF NOT EXISTS`, `CREATE OR REPLACE`), as the existing ones are ([doc 30](30-database-schema.md)).
- A destructive change (DROP, TRUNCATE, mass DELETE) and any production migration needs the owner's approval first. 0009 is the only existing migration with a DROP, and it stops first if data would be lost.
- After applying, run the privilege tests in `sql/tests/dataset_privilege_tests.sql` and update [doc 30](30-database-schema.md).
- Do not change a grant on a base table without reviewing PII exposure.

## Rotating secrets

Never paste a secret into chat, a commit, a log or an issue. Write it into `.env` yourself.

| Secret | Where it is used | Steps |
|---|---|---|
| `astra_analyst` password | `.env` (`DATABASE_PASSWORD`), ETL | Run `ALTER ROLE astra_analyst PASSWORD '<new>'` in the Supabase SQL editor. Update `.env`. Run `.\astra check-db` |
| `astra_reporting` password | `.env` (`REPORTING_DB_PASSWORD`), n8n credential, Looker Studio data source | `ALTER ROLE astra_reporting PASSWORD '<new>'`. Update `.env`, the n8n credential `Astra reporting (read-only)` and the Looker Studio data source. Run `.\astra check-db` |
| Telegram bot token | `.env` (`TELEGRAM_BOT_TOKEN`) | Create a new token in @BotFather. Update `.env`. Run `.\astra notify check --online` |
| Gemini API key | `.env` (`LLM_MODEL_KEY`), n8n credential `Google Gemini(PaLM) Api account` | Create a new key in Google AI Studio. Update `.env` and the n8n credential. Delete the old key |
| `LAYA_API_TOKEN` | `.env`, callers of the local Laya API | Set a new value in `.env` and restart `.\astra laya-api` |
| n8n encryption key | `config` file of each n8n | Do not rotate by hand. Keep the file backed up. Do not set `N8N_ENCRYPTION_KEY` in `.env` |

If a secret ever reached Git, rotate it at once. Removing it from history is not enough.

## Update the n8n workflow

1. Edit the spec in `src/astra_n8n` (for example `assistant.py`). Do not edit `n8n\build\`, it is generated.
2. Check and rebuild.

```powershell
.\astra n8n lint
```
```powershell
.\astra test
```
```powershell
.\astra n8n build
```

3. In the Astra n8n (`.\astra n8n-start`, then `http://astra.localhost:5698`), import `n8n\build\astra_data_assistant.json` again and check that credentials are attached.
4. Ask the 2025 net revenue question and compare with [doc 34](34-looker-studio-dashboards.md) and [doc 35](35-n8n-data-assistant.md).
5. To check the tools against the live database, run `.\astra n8n check-live`.

## Laya model updates

- Package and model revisions are pinned: [doc 23](23-laya-installation.md). Change them only after a new evaluation.
- Compare checkpoints with the evaluation harness (`.\astra laya-eval`) before any change. Results: [doc 27](27-laya-evaluation.md), choice: [doc 24](24-laya-model-selection.md).
- Resource use: [doc 29](29-laya-cost-and-resource-usage.md). Policy file: `config/laya_policy.json` ([doc 25](25-laya-decision-policy.md)). Auto-routing is off.
- After an update run `.\astra test` and `.\astra laya-test`.

## Open items (from STATUS)

| Item | State |
|---|---|
| Archive retention for `dataset.quarantine_archive` | Not implemented. It grows by one row per graduated or dropped row |
| Flow for updating already loaded master data | Not implemented. A new row with a loaded key is quarantined as `DUPLICATE_PRIMARY_KEY` |
| `public.rls_auto_enable()` advisor warning | Left unchanged. The function existed before these migrations. The owner decides |
| First scheduled run (2026-11-19 08:30): confirm the log and the Telegram message | Open |
| Looker Studio report (H5) | Open, a person builds it from [doc 34](34-looker-studio-dashboards.md) |
| Telegram chat for the data assistant | Not implemented. Needs a public webhook decision ([doc 35](35-n8n-data-assistant.md)) |
| The 17 test cases of the specification (Phase 11) | Not done ([doc 19](19-testing-and-validation.md)) |

Current status of all phases: [STATUS](STATUS.md).
