# Implementation Status — Astra Enterprise Data Analytics & AI Platform (SYNTHETIC)

Last updated: 2026-11-17. All data in this project is synthetic. Nothing here reflects
Astra International internal systems, data, or processes.

Legend: DONE = verified in this session · PARTIAL = some sub-tasks done · TODO = not started ·
BLOCKED = waits on a human step (see [HUMAN-STEPS.md](HUMAN-STEPS.md)).

## Phase table

| # | Phase | Status | Done so far (evidence) | Remaining | Human step needed |
|---|---|---|---|---|---|
| 1 | Environment discovery | DONE | Tool inventory below; n8n workflows/credentials listed read-only; raw files checksummed | — | — |
| 2 | Repository & skill integration | PARTIAL | Already present: `caveman@caveman` plugin, `rtk 0.49.0`, `data-analytics-skills@claude-code-skills`, `data-engineering@data-with-baraa` + `*@data-engineering-skills` plugins | Inspect & verify the two farisradifana skill repos are the installed sources; install CodeGraph and Graphify after README/LICENSE review | H2 (approve installs) |
| 3 | Data profiling | DONE | `scripts/profile_raw.py` → `reports/profiling/` (inventory, per-table JSON, FK checks, summary). Raw SHA-256 verified unchanged after run (10/10 OK) | Data dictionary draft (`docs/05-data-dictionary.md`) | — |
| 4 | Architecture & blueprint | TODO | Findings below define the rules | Target DDL, data contracts, error-code catalogue, ETL/notification/analytics design docs | D1–D6 data-rule decisions |
| 5 | Python ETL | TODO | — | extract/standardize/cleanse/dedupe/validate/quarantine/transform/load/notify/pipeline/reprocess modules + tests | Install `psycopg[binary]`, `pandera`, `pytest` (I can do it on approval) |
| 6 | PostgreSQL (Supabase) | BLOCKED | Decision: Supabase hosted Postgres 17. Project "AI Data Analyst Astra" created by user, status healthy (ap-southeast-1). Local install no longer needed | Migrations: roles, schema `dataset`, tables, RLS, grants; transactional load | **H1** Session-pooler values, CA cert, role passwords in `.env` |
| 7 | Telegram alerts | BLOCKED | No Telegram credential in n8n; no bot config in project | Notifier with retry/backoff/rate limit; test each alert category | **H3** bot token, chat ID, thread ID; approve test message |
| 8 | Looker Studio | BLOCKED | Connectivity decided: Looker Studio → Supabase Session pooler, SSL, read-only `astra_reporting` | Dashboard specs, KPI defs | **H5** build report in browser after Phase 6 |
| 9 | n8n + LLM AI Agent (`LLM_MODEL`, Gemini first) | PARTIAL | n8n 2.35.7 installed; Gemini credential exists (`googlePalmApi`); existing `Customer service agent` workflow already uses Agent + Gemini + window memory (reference only, not modified). **No existing Radifan Telegram bot workflow found in this n8n instance** | New workflows: Looker Studio assistant, Telegram assistant, read-only SQL tool, Postgres chat memory | **H3**, **H4** (`LLM_MODEL`/`LLM_MODEL_KEY`, Telegram allowlist, n8n Postgres credential); tell Claude where the existing bot runs |
| 10 | Documentation & automation | PARTIAL | `docs/STATUS.md`, `docs/HUMAN-STEPS.md`, profiling summary, Laya docs 22–29, `.env.example` | docs 00–21, Task Scheduler job, backup/restore runbook | **H6** approve scheduled task |
| 11 | Testing & final review | TODO | — | 17 test cases from spec, reconciliation, final report | — |
| 12 | Global skill | TODO | — | `%USERPROFILE%\.claude\skills\astra-enterprise-data-platform\SKILL.md` + discovery check | — |
| L | Laya local decision engine | PARTIAL | `laya==0.4.35` in `.venv-laya` (CPU torch 2.15.0); 3 checkpoints benchmarked; multilingual selected; engine, policy, fallback, eval harness; local FastAPI `api.py` on 127.0.0.1:8765 (bearer token) smoke-tested with real model; 44 unit/API + 5 real-model tests pass (offline) | n8n `ASTRA_LAYA_DECISION_ENGINE`, Telegram routing, held-out eval set, verify Ctrl+C shutdown | Put `LAYA_API_TOKEN` in `.env`; decide whether to keep auto-routing off |
| — | GitHub backup | DONE | Public repo `farisradifana/ai-data-analyst-astra` (user decision: public prototype); raw-data, `.env`, secrets, weights excluded | Push after each milestone | — |

## Phase 1 — environment inventory (verified 2026-11-17)

| Component | Found | Version / detail |
|---|---|---|
| OS | yes | Windows 11 Enterprise 10.0.26300 |
| Python | yes | 3.12.1 (also uv CPython 3.11.16) |
| pandas / numpy / SQLAlchemy | yes | 2.2.3 / 2.2.0 / 2.0.46 |
| pydantic / python-dotenv / openpyxl / charset-normalizer | yes | 2.13.4 / 1.2.2 / 3.1.5 / 3.4.0 |
| psycopg / pandera / pytest | **no** | must be installed |
| PostgreSQL server + `psql` | **no** | no service, port 5432 not listening |
| Navicat | **no** (not in Program Files) | user may have it elsewhere |
| Node.js / n8n | yes | v24.18.0 / n8n 2.35.7, data in `%USERPROFILE%\.n8n` (SQLite) |
| Docker | no | not required |
| Git | yes | 2.55.0 (project was not a repo) |
| rtk | yes | 0.49.0 |
| CodeGraph / Graphify | **no** | not on PATH |

n8n workflows (read-only listing): Trial, Nathan Workflow, Merging Data, Generating Reports,
Monitor Report Errors (active), Customer service agent. Credentials present by name only:
OpenAI, Anthropic, NVIDIA, Daytona, Discord webhooks, n8n API key, Google Gemini. No Telegram,
no PostgreSQL credential. Nothing was changed.

## Phase 3 — profiling headline (verified by `scripts/profile_raw.py`)

- 10 CSV files, UTF-8 with BOM, comma-delimited, 40.5 MB, **435,200 data rows**.
- **700 exact duplicate rows**; every duplicate primary key is an exact full-row duplicate
  (`pk_duplicates_not_exact = 0` in all tables). Policy candidate: keep first, log the rest.
- **Dates**: every date column mixes 4 formats ~25% each: `YYYY-MM-DD`, `YYYY/MM/DD`,
  `DD/MM/YYYY`, `MM-DD-YYYY`. No unrecognised strings.
  Inferred rule (needs confirmation, D1): slash + year-last = day-first; dash + year-last = month-first.
  Evidence: `03-22-2026` (month 22 impossible as day-first), `25/12/2025`.
- **Money**: mixed `Rp 1,353,708`, `1,353,708.00`, plain, padded. Invalid tokens `unknown`
  (expenses.amount, 28), `TBD` (products.list_price, 39). Negatives: expenses.amount 47,
  products.list_price 33.
- **Numeric**: sales.quantity has `two`-style words (99), negatives (107), zero (94);
  inventory.quantity_on_hand `N/A` (28), negative (37); discount_pct mixes `5` and `5%`.
- **Categories**: casing/whitespace noise everywhere (e.g. branch 24 raw → 6 normalised).
  `products.active_flag` uses Y/N/1/0/YES; `suppliers.payment_terms` has `NET30` / `NET 30` / `30 DAYS` (same meaning? D2).
  `warehouse_code` case variants (`Wh-Tgr-01`) → 4 codes.
- **Missing**: customers.city sentinels `N/A`/`NULL` (189); customers.email/phone sentinels
  (220 / 181); employees.manager_id blank 19 (could be top-level managers).
- **Orphan FKs**: placeholder IDs `EMP99999`, `CUS999999`, `PRD99999`, `SUP9999`, and
  wrong-entity IDs (e.g. a `PRD…` value in `procurement.supplier_id`). Sales: 245–261 per FK column.
- Phone numbers have leading zeros → store as `VARCHAR`, never numeric.

Open decisions: D1 date rule, D2 payment-terms mapping, D3 negative/zero quantity policy,
D4 negative amounts (refunds vs errors). Defaults proposed in [HUMAN-STEPS.md](HUMAN-STEPS.md).

## Laya — evaluation headline (2026-11-17, details in docs/27-laya-evaluation.md)

| Checkpoint | DQ acc (EN/ID) | Routing acc (EN/ID) | p50 latency | Peak RAM |
|---|---|---|---|---|
| multilingual (selected) | 0.600 (0.65/0.55) | 0.688 (0.81/0.56) | ~1.0–1.2 s | ~2.2 GB |
| english | 0.575 (0.70/0.45) | 0.625 (0.81/0.44) | ~2.7 s | ≤3.0 GB |
| typed-decisions | 0.600 (0.75/0.45) | 0.719 (0.88/0.56) | ~2.9–3.5 s | ≤3.0 GB |

Auto-routing is disabled for both tasks (`config/laya_policy.json`). The set is small
(40 + 32 items), so these numbers are indicative only.
