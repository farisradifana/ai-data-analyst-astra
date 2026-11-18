# 21 — Change log

Last checked: 2026-11-18

Built from `git log` (date, short hash, subject). Newest first. Dates are commit dates.


## 2026-11-18

- H9 done: live Telegram question answered through the bridge; 404 and webhook troubleshooting notes (doc 36, H9)
- Telegram bridge: answer @mentions and replies to the bot in the group (topics too); privacy-mode note (doc 36, H9)
- Telegram chat for the data assistant: local bridge `.\astra telegram-bot` (doc 36) and webhook workflow `ASTRA_TELEGRAM_ASSISTANT`; Looker Studio CUSTOM QUERY note (doc 34, H5); spec cases 16 and 17 recorded
- `3a52dc3` Phase 12: global Claude Code skill astra-enterprise-data-platform
- Phase 12: global Claude Code skill `astra-enterprise-data-platform` (repo copy in `skill/`, installed to the user skills folder); STATUS phase table refreshed
- `9b38885` Phase 11: spec test cases, live reconciliation, final report
- `9bbd556` Docs: dated top-level raw files are intentionally not loaded (user decision)
- `f69310d` Phase 10: docs 00-21, CLAUDE.md, requirements.txt
- `e2cdb03` Docs: Phase 9 data assistant verified live in n8n (H4 done)
- `7b0ea91` n8n-start: set N8N_SECURE_COOKIE=false for the loopback-only astra.localhost editor
- `d32a282` n8n-start: open the Astra n8n as astra.localhost:5698
- `10beb2b` n8n-start: separate Astra n8n (own data folder, task runner port 5699)
- `20cd85f` Add .\astra n8n-start: n8n editor on 127.0.0.1:5698 with the Supabase CA trusted
- `3ac5ff0` Docs: n8n Postgres credential has no CA field; trust the Supabase CA via NODE_EXTRA_CA_CERTS
- `4a653d6` Add n8n data assistant workflow (Phase 9, doc 35)
- `cd6fbf7` Add KPI and quarantine-monitor views for Looker Studio (migration 0010, doc 34)
- `88fb018` Record H6 done: daily ETL task registered at 08:30 WIB
- `58a8c46` Add daily ETL job for Task Scheduler; fix launcher exit codes
- `35179b4` Record H3 done: Telegram test delivered to the configured topic
- `f1fa212` Add Telegram ETL alerts (counts only, retry and rate limit)
- `836e2a6` Drop unused legacy quarantine_correction table (migration 0009)
- `0bcf7cc` Read each file once; fix and graduate rows inside quarantine
- `7204e15` Add astra.cmd launcher; Windows-ready commands in docs
- `7df0f07` Fix quarantined rows in the database, not the CSV

## 2026-11-17

- `dcbb332` Load ETL to Supabase with labelled, graduating quarantine
- `5cbdfd5` Mark H1 done: both Supabase roles verified with verify-full SSL
- `27d6205` Add DB connection check; fix pooler host and n8n key guidance
- `41bfaf5` Apply Supabase migrations; record test and advisor results
- `637c527` Add Supabase migrations for schema dataset (not yet applied)
- `97ef2a2` Add local Laya FastAPI service (127.0.0.1, bearer token)
- `b1dc7e7` Add Laya local decision engine, Supabase plan, provider-neutral LLM vars
- `5a7d041` Phase 1: environment discovery and raw data profiling
- `7582de7` Initial commit

Later work is not listed until it is committed. Status of each phase: [STATUS](STATUS.md).
