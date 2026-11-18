# 15 — Security and access

Last checked: 2026-11-18

Roles, secrets, environment variables, dependencies and network exposure. Database detail: [doc 30](30-database-schema.md).
All data is SYNTHETIC. The repository is public, so no secret or identifier may be committed.

## Roles and least privilege

| Role | Used by | Privileges |
|---|---|---|
| `astra_analyst` | ETL (`.\astra etl`, `.\astra fix`) | SELECT, INSERT, UPDATE on `dataset` tables. DELETE only on `quarantine_record`. No TRUNCATE, no DDL |
| `astra_reporting` | Looker Studio, n8n data assistant, `check-live` | SELECT on PII-free tables and the `v_*` views. Column-level SELECT elsewhere. No write. Session default is read-only |
| `anon`, `authenticated`, PUBLIC | nobody | No access to `dataset` |

- The roles are created without a password. The owner sets the passwords in Supabase; they live in `.env` only.
- The ETL connects as `<role>.<project_ref>` through the Session pooler.
- `dataset` must stay out of the Supabase Data API "exposed schemas" list.

## PII denial

`astra_reporting` cannot read names, emails, phones, salaries, `raw_record`, `issue_detail`, `record_key` or `depends_on`.
`SELECT *` on `customers`, `employees` and `suppliers` is denied by design. Reports and the n8n tools use aggregated `v_*` views.
The Telegram alerts carry counts only ([doc 32](32-telegram-alerts.md)).
`sql/tests/dataset_privilege_tests.sql` checks the denials, and always rolls back.

## Row Level Security

RLS is enabled on every table in `dataset`, with explicit per-role policies.
The policies are `true` for the two app roles, because the data is single-tenant and synthetic. Isolation comes from role privileges and column grants.
Known open item: the pre-existing `public.rls_auto_enable()` function (SECURITY DEFINER, executable by `anon`/`authenticated`) was not created by these migrations and is unchanged, pending an owner decision ([doc 30](30-database-schema.md), advisors).

## Database connection

- Session pooler, `DATABASE_SSLMODE=verify-full`, with the Supabase CA in `secrets/supabase-ca.crt`. If `verify-ca` or `verify-full` is set and the file is missing, the connection stops with an error.
- The code default is `verify-full` when `DATABASE_SSLMODE` is empty.
- n8n trusts the same CA through `NODE_EXTRA_CA_CERTS` (set by `.\astra n8n-start`). Keep "Ignore SSL Issues" off in the n8n credential.
- Queries use bound parameters. The n8n tools take typed values as `$1`, `$2`, ... and `.\astra n8n lint` rejects unsafe SQL ([doc 35](35-n8n-data-assistant.md)).

## Secret handling

- `.env` is untracked (`.gitignore`: `.env`, `.env.*`, with `!.env.example`). `.env.example` holds names and placeholders only.
- `secrets/`, `*.crt` and `*.pem` are ignored by Git.
- `raw-data/`, `logs/`, `n8n/build/`, `.venv-*/` and model files are ignored.
- Public repo rule: never commit a password, API key, bot token, Supabase project ref, Telegram chat/thread/user id or e-mail address. Docs use placeholders such as `<project_ref>`.
- The Telegram bot token is removed from error text and never printed ([doc 32](32-telegram-alerts.md)).
- n8n credentials live in `%USERPROFILE%\.n8n-astra`, outside the repo. Back up its `config` file in a password manager.
- If a secret leaks, rotate it. Rewriting Git history is not enough.

## Environment variables (`.env.example`)

`.env` is read by `astra_etl.db.load_env` (python-dotenv). "Read by" lists where the code uses the name.

| Variable | Purpose | Read by |
|---|---|---|
| `SUPABASE_PROJECT_REF` | 20-character project ref, appended to the DB user name | `src/astra_etl/db.py`, `scripts/check_db_connection.py` |
| `DATABASE_HOST` | Session pooler host | same |
| `DATABASE_PORT` | Pooler port (default 5432) | same |
| `DATABASE_NAME` | Database (default `postgres`) | same |
| `DATABASE_SCHEMA` | Schema name `dataset` | `scripts/check_db_connection.py` (checked as set; the SQL names `dataset` directly) |
| `DATABASE_SSLMODE` | SSL mode (`verify-full`) | `src/astra_etl/db.py`, `scripts/check_db_connection.py` |
| `DATABASE_SSLROOTCERT` | Path to the CA file | same |
| `DATABASE_USER` | ETL writer role (`astra_analyst`) | same |
| `DATABASE_PASSWORD` | Writer password | same |
| `REPORTING_DB_USER` | Read-only role (`astra_reporting`) | same |
| `REPORTING_DB_PASSWORD` | Read-only password | same |
| `TELEGRAM_BOT_TOKEN` | Bot token for alerts | `src/astra_etl/notify.py` |
| `TELEGRAM_CHAT_ID` | Target chat | `src/astra_etl/notify.py` |
| `TELEGRAM_MESSAGE_THREAD_ID` | Optional topic | `src/astra_etl/notify.py` |
| `TELEGRAM_ALLOWED_USER_IDS` | Reserved for a future Telegram chat | Not read by any code today |
| `LLM_MODEL` | Gemini model id for the workflow | `src/astra_n8n/__main__.py`, `src/astra_n8n/assistant.py` (`model_name`) |
| `LLM_MODEL_KEY` | Reserved for the LLM key | Not read by any code today. The key is an n8n credential |
| `N8N_BASE_URL` | Address of the Astra n8n | Not read by any code today. The launcher sets `N8N_EDITOR_BASE_URL` itself |
| `N8N_ENCRYPTION_KEY` | Keep **empty**. n8n keeps its own key; a different value stops n8n with "Mismatching encryption keys" | Read by n8n itself, not by project code |
| `LAYA_CHECKPOINT` | Laya model checkpoint (default `multilingual`) | `src/decision_engine/model_manager.py` |
| `LAYA_THREADS` | CPU threads for inference (default 4) | `src/decision_engine/model_manager.py` |
| `LAYA_API_HOST` | Laya API bind address (default `127.0.0.1`) | `src/decision_engine/api.py` |
| `LAYA_API_PORT` | Laya API port (8765) | `src/decision_engine/api.py` |
| `LAYA_API_TOKEN` | Bearer token for the Laya API. The server refuses to start with a token shorter than 16 characters | `src/decision_engine/api.py` |
| `HF_HUB_OFFLINE` | 1 forbids Hugging Face network access | `src/decision_engine/model_manager.py`; `astra.cmd` sets it to 1 for `laya-test` and `laya-api` |
| `HF_HUB_DISABLE_SYMLINKS_WARNING` | Hides a Hugging Face symlink warning on Windows | Read by the `huggingface_hub` library, not by project code |

The Laya API also honours `LAYA_API_ALLOW_REMOTE` (not in `.env.example`). Leave it unset: with it, a non-loopback bind is allowed.

## Dependencies

Install commands and pins: `requirements.txt` (system Python 3.12) and `requirements-laya.txt` (`.venv-laya`).
Licences below were read from installed package metadata on 2026-11-18. They are not legal advice.

| Component | Version | Licence |
|---|---|---|
| psycopg2-binary | 2.9.11 | LGPL with exceptions |
| python-dotenv | 1.2.2 | BSD-3-Clause |
| pandas | 2.2.3 | BSD-3-Clause |
| n8n | 2.35.7 | "SEE LICENSE IN LICENSE.md" (n8n's own source-available licence; not checked in detail) |
| Node.js | v24.18.0 | licence not checked |

Laya environment (`requirements-laya.txt`, 56 pinned packages). Main packages and licences from metadata:

| Package | Version | Licence |
|---|---|---|
| laya | 0.4.35 | Apache Software License |
| transformers | 5.23.0 | Apache 2.0 |
| tokenizers | 0.23.3 | Apache Software License |
| huggingface_hub | 2.4.0 | Apache Software License |
| safetensors | 0.8.0 | Apache Software License |
| numpy | 2.5.5 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| fastapi | 0.163.1 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| uvicorn | 0.54.0 | BSD-3-Clause |
| pydantic | 2.14.3 | MIT |
| pytest | 9.2.0 | MIT |
| certifi | 2026.10.23 | MPL 2.0 |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |

Licences of the other pinned packages in `requirements-laya.txt` are in each package's metadata (all are permissive or weak-copyleft: MIT, MIT-0, BSD, Apache-2.0, ISC, PSF-2.0, MPL-2.0, and `regex` is Apache-2.0 AND CNRI-Python).
PyTorch (CPU wheel 2.15.0, installed separately, see the header of `requirements-laya.txt`): licence not checked.
The Laya model weights (Hugging Face): licence not checked here; see [doc 24](24-laya-model-selection.md).

Audit: no dependency audit tool (`pip-audit`, `npm audit`) was run for this document.

## Network exposure

| What | Listens on | Reachable from |
|---|---|---|
| Astra n8n editor | `127.0.0.1:5698` (opened as http://astra.localhost:5698) | This PC only |
| n8n task runner broker | `127.0.0.1:5699` | This PC only |
| Laya API (`.\astra laya-api`) | `127.0.0.1:8765`, bearer token required | This PC only. Refuses a non-loopback host unless `LAYA_API_ALLOW_REMOTE=1` |

- The chat trigger of `ASTRA_DATA_ASSISTANT` is not public, and the workflow is imported inactive.
- Outbound only: ETL and n8n to the Supabase pooler (TLS, verified); the ETL to `api.telegram.org`; n8n to Google's Gemini API.
- Looker Studio connects from Google's cloud to the Supabase pooler as `astra_reporting`.
- Nothing is deployed or exposed to the internet by this project.
