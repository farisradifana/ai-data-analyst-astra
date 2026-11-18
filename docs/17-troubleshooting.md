# 17 — Troubleshooting

Last checked: 2026-11-18

Problems that happened in this project, with the fix. Run commands from the project folder, in PowerShell or cmd.

## Database connection

| Symptom | Cause | Fix |
|---|---|---|
| "tenant/user not found" when connecting | The Session pooler host is `aws-0-...`. This project uses `aws-1` | Copy the host from Supabase, Connect, Session pooler. In `.env` it starts with `aws-1-` |
| Connection hangs or "network unreachable" on the direct host | The direct database host is IPv6 only | Use the Session pooler host, port 5432 |
| Errors about prepared statements | Port 6543 is the transaction pooler. It breaks prepared statements | Use port 5432 (Session pooler) |
| `self-signed certificate in certificate chain` (n8n) or an SSL verify error (Python) | The Supabase chain is not in the system trust store | Python: keep `DATABASE_SSLMODE=verify-full` and `DATABASE_SSLROOTCERT=secrets/supabase-ca.crt`. n8n: start it with `.\astra n8n-start`, which sets `NODE_EXTRA_CA_CERTS`. Do not turn on "Ignore SSL Issues" |
| "CA certificate not found at ..." | `secrets\supabase-ca.crt` is missing | Download the certificate again (Supabase, Settings, Database, SSL certificate) and save it there |
| "SUPABASE_PROJECT_REF must be the 20-char project ref" | `.env` has a URL or a wrong value | Put the 20-character ref only. The code builds the login as `<role>.<project_ref>` itself, so `DATABASE_USER` is the plain role name |
| Login refused, project does not answer | Supabase free tier pauses a project after about 7 days without activity | Open the dashboard and restore the project. Then run the ETL or open the dashboard at least weekly |

Test the connection. It prints variable names and results, never values:

```powershell
.\astra check-db
```

## n8n

| Symptom | Cause | Fix |
|---|---|---|
| "Unauthorized" when you save a workflow | Browser cookies ignore the port. Another n8n on `127.0.0.1` overwrites the login cookie of the Astra n8n | Open the editor as `http://astra.localhost:5698`, never `127.0.0.1:5698` |
| Page says n8n is "configured to use a secure cookie" | The editor runs on plain HTTP | `.\astra n8n-start` sets `N8N_SECURE_COOKIE=false`. Safe only because it listens on 127.0.0.1. Do not copy this setting to a reachable n8n. Restart n8n after changing it |
| `n8n start` in your own `.cmd` file ends the script early | `n8n` is a batch shim (`n8n.cmd`) | Write `call n8n start` in a batch file. `astra.cmd` already does |
| Task broker port 5679 is in use | The other n8n already uses the default task runner port | The Astra n8n uses `N8N_RUNNERS_BROKER_PORT=5699`, set by `.\astra n8n-start` |
| n8n refuses to start with a key mismatch | `N8N_ENCRYPTION_KEY` in `.env` differs from the key in the n8n `config` file | Leave `N8N_ENCRYPTION_KEY` empty in `.env` |
| Credentials unreadable after a reinstall | The `config` file with the encryption key was lost | Restore it from the password manager. See [doc 16](16-automation-runbook.md) |

Start the Astra n8n:

```powershell
.\astra n8n-start
```

### Gemini and the model id

| Symptom | Cause | Fix |
|---|---|---|
| "resource ... could not be found" in the chat model node | The API key has no access to that model id. Seen with `gemini-3.6-flash` | Use a model id the key can use. The working one is `gemini-3.5-flash` |
| Chat looks frozen for minutes, "too many requests" in the execution log | Rate limit. n8n retries quietly. Seen with `gemini-3.8-flash` | Check the model quota in Google AI Studio. Switch model or wait |
| `LLM_MODEL` is rejected by `.\astra n8n build` | A `provider/model` id was used | Use a plain Gemini id, with no provider prefix |
| Model node shows `SET_LLM_MODEL` | `LLM_MODEL` is empty in `.env` | Set it, then run `.\astra n8n build` and import again |

After changing `LLM_MODEL`, rebuild, then import the file again:

```powershell
.\astra n8n build
```

Details: [doc 35](35-n8n-data-assistant.md).

## Launcher

| Symptom | Cause | Fix |
|---|---|---|
| Commands in `astra.cmd` fail or labels are not found | `astra.cmd` lost its CRLF line endings | Rewrite the file with CRLF. Then run `.\astra bogus`: it must exit with code 2 |
| `.\astra` prints only usage | No command given. It never starts a load | Add a command, for example `.\astra etl --dry-run` |
| `ModuleNotFoundError: astra_etl` when you run `python -m astra_etl` yourself | `PYTHONPATH` is not set | Use `.\astra etl ...`. The launcher sets `PYTHONPATH` to `src` |
| A scheduled run shows result 124 | The job hit its 30 minute limit | Read the log in `logs\etl`. A `JOB_TIMEOUT` alert was sent. See [doc 33](33-daily-schedule.md) |

## ETL and quarantine

These are covered in [doc 31](31-etl-and-quarantine.md). The most common ones:

| Symptom | Fix |
|---|---|
| "another ETL run is in progress" | Wait for the other run. The lock is released when its connection closes |
| "`<file>` changed after it was loaded" | Restore the original file. Send new data as a new file in `raw-data\<table>\` |
| A new file is skipped with "same content as a file already loaded" | Expected. A file with the same content is never loaded twice |
| A row stays in quarantine after a fix | Run `.\astra fix show <table> <key>`. The failing column is marked `<- fix`. The rule can change after a fix |
| Rows wait on a parent (`ORPHAN_PARENT_QUARANTINED`) | Fix the parent named in `depends_on`. The children graduate in the same run |
| A row has a blank key | Use `-` as KEY together with `--id N` |
| New values for an already loaded key are quarantined as `DUPLICATE_PRIMARY_KEY` | A flow for updating loaded master data does not exist yet (Not implemented) |

Fix commands: see [doc 16](16-automation-runbook.md).

## Laya

Symptoms and fixes for the local decision engine (symlink warning, import hang, slow first run, memory, fallback decisions) are in [doc 28](28-laya-troubleshooting.md). Install steps: [doc 23](23-laya-installation.md).

## Alerts

Alert categories, retry rules and the offline checks are in [doc 32](32-telegram-alerts.md). To test the setup without sending a message:

```powershell
.\astra notify check
```
