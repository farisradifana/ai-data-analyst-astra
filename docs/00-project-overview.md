# 00 — Project overview

Last checked: 2026-11-18

## Purpose

Astra is a data analytics and AI platform prototype. It loads messy business CSV files into a clean PostgreSQL schema,
reports on them in Looker Studio, answers questions about them in an n8n chat assistant, and alerts on data quality through Telegram.
It also holds a local decision engine (Laya) for classification tasks.

## Synthetic data disclaimer

All data is synthetic. The project is a simulation in the style of an Astra International Sunter operation.
It is not affiliated with Astra International. No internal data, systems or processes of that company are used.
Nothing in this repo describes a real company, customer, employee or supplier.
The GitHub repo is public by user decision. Raw data, `.env`, `secrets/` and model weights are excluded from Git.

## Components

| Component | Where | Doc |
|---|---|---|
| Python ETL (pure Python + psycopg2) | `src/astra_etl` | [31](31-etl-and-quarantine.md) |
| Supabase PostgreSQL, schema `dataset` | `sql/migrations/` (10 migrations) | [30](30-database-schema.md), [03](03-data-architecture.md) |
| Quarantine and `.\astra fix` | `src/astra_etl/fix.py` | [31](31-etl-and-quarantine.md) |
| Telegram alerts (counts only) | `src/astra_etl/notify.py` | [32](32-telegram-alerts.md) |
| Daily job in Task Scheduler | `scripts/daily_etl.ps1`, `scripts/register_daily_task.ps1` | [33](33-daily-schedule.md) |
| Looker Studio report spec and KPIs | views from migration 0010 | [34](34-looker-studio-dashboards.md) |
| n8n data assistant with Gemini | `src/astra_n8n` | [35](35-n8n-data-assistant.md) |
| Laya local decision engine and API | `src/decision_engine` | [22](22-laya-architecture.md)–[29](29-laya-cost-and-resource-usage.md) |
| Launcher | `astra.cmd`, used as `.\astra <command>` | run `.\astra` for the usage |

Architecture: [doc 02](02-system-blueprint.md).

## Status (from [STATUS](STATUS.md), 2026-11-18)

Done:

- Environment discovery and raw data profiling (10 files, 435,200 rows).
- PostgreSQL schema, roles, RLS, grants and reporting views. Privilege tests 13 of 13 pass. Database connection verified for both roles.
- First load on 2026-11-17: 435,200 rows read, 428,516 loaded, 5,984 quarantined, 700 exact duplicates.
  Since then each file is read once and the quarantine holds only rows still to fix. The ETL has 73 unit tests.
- Telegram alerts verified online with a test message. Alert logic is covered by offline tests.
- Daily task "Astra Daily ETL" registered for 08:30 WIB (first scheduled run on 2026-11-19).
- n8n data assistant imported into a separate local n8n and verified with a live question (2025 net revenue matched the reference).
- GitHub backup.

Open:

- Looker Studio report: the spec is written, the report is not built yet (human step H5).
- A live Telegram alert from a real scheduled load, and confirmation of the first scheduled run.
- Updating already-loaded master data (a changed price is quarantined as a duplicate key). Not implemented. Archive retention is also open.
- Telegram chat front end for the assistant: needs a public webhook, so it needs a decision.
- Laya: n8n workflow `ASTRA_LAYA_DECISION_ENGINE`, Telegram routing and a held-out evaluation set are not built. Auto-routing is off.
- Decision on the existing Supabase advisor warning about `public.rls_auto_enable()`.
- Phase 2 skill tool installs (CodeGraph, Graphify).
- Backup and restore: written in [doc 16](16-automation-runbook.md), but the `pg_dump` / restore commands are not tested
  (no PostgreSQL client on this PC).

Steps that need a person: [HUMAN-STEPS](HUMAN-STEPS.md).

## Document map

| Doc | Topic |
|---|---|
| [00](00-project-overview.md) | This page |
| [01](01-business-context.md) | The simulated business, questions and KPIs |
| [02](02-system-blueprint.md) | Components, data flow, trust boundaries (diagram) |
| [03](03-data-architecture.md) | Schema layers and table relationships (diagram) |
| [04](04-source-inventory.md) | The 10 source CSVs, checksums, file layout |
| [05](05-data-dictionary.md) | Every column of every core table |
| [06](06-data-quality-rules.md) | Data quality rules |
| [07](07-etl-workflow.md) | ETL workflow |
| [08](08-python-documentation.md) | Python modules, scripts and CLI reference |
| [09](09-postgresql-documentation.md) | PostgreSQL tables, views, roles and grants |
| [10](10-sql-reference.md) | SQL files and example queries |
| [11](11-telegram-alerting.md) | Telegram alerting |
| [12](12-looker-studio.md) | Looker Studio |
| [13](13-n8n-ai-agent.md) | n8n AI agent |
| [14](14-gemini-integration.md) | Gemini integration |
| [15](15-security-and-access.md) | Security and access |
| [16](16-automation-runbook.md) | Automation runbook |
| [17](17-troubleshooting.md) | Troubleshooting |
| [18](18-deployment-guide.md) | Deployment guide (new Windows PC) |
| [19](19-testing-and-validation.md) | Testing and validation |
| [20](20-maintenance.md) | Maintenance |
| [21](21-change-log.md) | Change log |
| [22](22-laya-architecture.md) | Laya architecture |
| [23](23-laya-installation.md) | Laya installation |
| [24](24-laya-model-selection.md) | Laya model selection |
| [25](25-laya-decision-policy.md) | Laya decision policy |
| [26](26-laya-n8n-integration.md) | Laya local API and n8n integration |
| [27](27-laya-evaluation.md) | Laya evaluation |
| [28](28-laya-troubleshooting.md) | Laya troubleshooting |
| [29](29-laya-cost-and-resource-usage.md) | Laya cost and resource usage |
| [30](30-database-schema.md) | Database schema, grants, views, privilege tests |
| [31](31-etl-and-quarantine.md) | ETL run and quarantine lifecycle |
| [32](32-telegram-alerts.md) | Telegram alerts |
| [33](33-daily-schedule.md) | Daily job and Task Scheduler |
| [34](34-looker-studio-dashboards.md) | KPI catalogue and dashboard spec |
| [35](35-n8n-data-assistant.md) | n8n data assistant |

Also: [STATUS](STATUS.md) (progress) and [HUMAN-STEPS](HUMAN-STEPS.md) (steps that need a person).

## Quick start

From the project folder, in PowerShell or cmd. These commands are safe: neither writes to the database.

```powershell
.\astra
```
```powershell
.\astra etl --dry-run --offline
```
```powershell
.\astra n8n lint
```

- The first prints the command list.
- The second validates the source files without any database connection.
- The third checks the assistant's SQL tools offline.

## Global Claude Code skill

The repo keeps a reusable skill, `skill/astra-enterprise-data-platform/` (SKILL.md and `references/`). It holds the
platform's standards and procedures and no credentials. Claude Code loads it in any project once it is copied to the
user skills folder. Install or update it from the repo root in PowerShell:

```powershell
Copy-Item -Recurse -Force skill\astra-enterprise-data-platform "$env:USERPROFILE\.claude\skills\"
```

Start a new Claude Code session afterwards: the skill list is read at session start. Check with
`/astra-enterprise-data-platform`, or ask Claude whether the skill is listed.
