---
name: astra-enterprise-data-platform
description: Build, run, extend or troubleshoot a CSV-to-PostgreSQL analytics platform in the Astra pattern - Python ETL with a live quarantine, Supabase/PostgreSQL schema `dataset` with read-only reporting views, Looker Studio dashboards, an n8n AI agent on Gemini with fixed parameterized SQL tools, and counts-only Telegram alerts, on Windows. Use when working in the ai-data-analyst-astra repo, or when asked to set up a similar data-quality ETL, quarantine/reprocessing flow, reporting views for Looker Studio, an n8n data assistant over PostgreSQL, or ETL alerting to Telegram.
---

# Astra enterprise data platform

A reusable recipe for a small, secure analytics platform. Reference implementation:
`https://github.com/farisradifana/ai-data-analyst-astra` (public, SYNTHETIC data). In that repo, its
`CLAUDE.md`, `docs/STATUS.md` and `docs/00-project-overview.md` override this skill on project facts.

## When to use

- The task touches the Astra repo (`astra.cmd`, `src/astra_etl`, `src/astra_n8n`, `sql/migrations`, `docs/00-35`).
- A user wants: raw CSV/Excel → validated PostgreSQL tables with a quarantine for bad rows; Looker Studio on
  PostgreSQL; an LLM chat assistant over business data in n8n; ETL alerts in Telegram; a scheduled ETL on Windows.
- Debugging: Supabase connection or SSL errors, n8n credential/cookie errors, Gemini model or rate-limit errors,
  quarantine rows that never graduate, reconciliation mismatches.

## Required context (collect before acting)

1. `git status`, the project `CLAUDE.md`, `docs/STATUS.md`, `docs/HUMAN-STEPS.md`.
2. Which database: local PostgreSQL or Supabase (project ref is a secret-ish identifier: keep it in `.env` only).
3. Variable **names** from `.env.example`. Never read or print `.env` values.
4. Is the repo public? If yes, no project refs, chat/thread/user IDs, tokens or emails in any committed file.
5. Which steps need a human (passwords, API keys, sign-ins, dashboard building) → write them in `docs/HUMAN-STEPS.md`.

## System architecture

```
raw-data/<table>.csv + raw-data/<table>/*.csv
  → Python ETL (clean → validate → quarantine → load, one transaction, advisory lock)   [role: analyst, writer]
  → PostgreSQL schema `dataset`: core tables, quarantine_record/archive, etl_run*, source_file, dq_check_result
  → security_invoker views v_*                                                          [role: reporting, read-only, no PII]
  → Looker Studio (Session pooler, SSL) and n8n AI agent (Gemini + fixed SQL tools)
  → Telegram alerts (counts only) from the ETL; Windows Task Scheduler runs the daily job
```
Details and diagrams: [references/architecture.md](references/architecture.md).

## Standards (summary; each has a reference file)

| Topic | Rule | Reference |
|---|---|---|
| Data processing | Each source file is read once (SHA-256 registered); a changed registered file stops the run; new data comes as a new file | [etl-and-quality.md](references/etl-and-quality.md) |
| Python ETL | Pure-Python cleaners per column, rule catalog with ids, reconciliation `read = loaded + quarantined + duplicate` enforced every run | [etl-and-quality.md](references/etl-and-quality.md) |
| Data quality | No guessing: invalid values go to quarantine with a rule id and column names, never values; exact duplicates dropped and archived | [etl-and-quality.md](references/etl-and-quality.md) |
| PostgreSQL | One schema `dataset`; timestamped migrations, never edited once applied; RLS on every table; writer and read-only roles; PII column grants denied | [postgres-rules.md](references/postgres-rules.md) |
| Looker Studio | Reads only `v_*` views as the reporting role over SSL; KPI catalogue with reference values to check each scorecard | [integrations.md](references/integrations.md) |
| n8n AI agent | LLM never writes SQL; each tool = one fixed SELECT on a view with `$n` parameters filled by `$fromAI`; workflow generated from code and linted | [integrations.md](references/integrations.md) |
| Gemini | Model id from `LLM_MODEL` (plain id, e.g. `gemini-2.5-flash`); key only in the n8n credential store; check quota first when chat hangs | [integrations.md](references/integrations.md) |
| Telegram | Counts only, never row data or error messages; retry with backoff, honour `retry_after`; an alert failure never fails the ETL | [integrations.md](references/integrations.md) |
| Security | Secrets in `.env`/credential stores; loopback-only services; no public DB; ask before destructive SQL, grants, sends, paid services | [security.md](references/security.md) |

## Procedures

### Run the ETL (Astra repo, PowerShell or cmd)
```powershell
.\astra etl --dry-run --offline
```
```powershell
.\astra etl --dry-run
```
```powershell
.\astra etl
```
Dry runs write nothing. `--offline` skips the database. A real run sends Telegram alerts unless `--no-notify`.

### Reprocessing rejected records
Rows are fixed **inside** quarantine; every run rechecks all of them.
```powershell
.\astra fix list --table products
```
```powershell
.\astra fix show products PRD00002
```
```powershell
.\astra fix set products PRD00002 list_price 125000 --reason "price confirmed by owner"
```
`.\astra fix drop <quarantine_id> --reason "..."` removes a row that must never load (archived, not deleted
silently). Then run `.\astra etl`: fixed rows graduate, and children waiting on a fixed parent graduate in the
same run. `.\astra fix history` shows every edit with its old value.
Full flow: [references/testing-and-reprocessing.md](references/testing-and-reprocessing.md).

### Change the database
New file `sql/migrations/<UTC timestamp>_<name>.sql` → review → user approval for anything destructive, any grant
or RLS change → apply → re-run the privilege checks and `.\astra etl --dry-run`.

### Change the n8n assistant
Edit the tool list in `src/astra_n8n/assistant.py` → `.\astra n8n lint` → `.\astra test` → `.\astra n8n check-live`
→ `.\astra n8n build` → re-import `n8n\build\astra_data_assistant.json` in the Astra n8n (`.\astra n8n-start`).

## Documentation rules

- Docs match the code; anything not built is written as "Not implemented", never as a placeholder.
- Keep `docs/STATUS.md` (evidence per phase) and `docs/HUMAN-STEPS.md` current at each milestone.
- User-facing commands run in Windows PowerShell 5.1 and cmd (prefer `.\astra <cmd>`), one per code block.
- Mermaid for architecture, ER, ETL flow and agent topology.

## Testing requirements

Gates, cheapest first: `python -m compileall -q src tests` → `.\astra test` → `.\astra n8n lint` →
`.\astra n8n check-live` → `.\astra etl --dry-run --offline` → `.\astra etl --dry-run`.
Never report a gate as passed unless it ran and passed. The 17 spec cases and the live reconciliation queries:
[references/testing-and-reprocessing.md](references/testing-and-reprocessing.md).

## Troubleshooting

Known failures and fixes (Supabase pooler/SSL, n8n cookies and secure cookie, `call n8n`, Gemini quota, CRLF in
`astra.cmd`, free-tier pause): [references/troubleshooting.md](references/troubleshooting.md).
