# Human Steps Guide

Steps only a person can do (installs needing admin rights, secrets, external accounts, approvals).
Do them in order. Never paste a password, token or API key into chat — put them in the
untracked `F:\data-analyst-astra\.env` file yourself. Mark each box when done.

---

## H1 — Supabase PostgreSQL (replaces local install; blocks Phase 6)

Decision 2026-11-17: PostgreSQL is hosted on Supabase so Looker Studio can reach it.
Project "AI Data Analyst Astra" exists (region ap-southeast-1, Postgres 17, status healthy).
The project ref is kept in `.env` only (`SUPABASE_PROJECT_REF`), not in this public repo.

Deviation from the original spec: Supabase's database name is always `postgres`, not
`astra_analytics`. Schema `dataset` and roles `astra_analyst` / `astra_reporting` are unchanged.

1. Supabase dashboard → project → **Connect** → **Session pooler**. Copy host, port `5432`,
   user format `<role>.<project_ref>`. Do not use the direct host (IPv6 only) or port 6543
   (transaction pooler; breaks prepared statements).
2. Settings → Database → **Download SSL certificate** (`prod-ca-2021.crt`). Save it to
   `F:\data-analyst-astra\secrets\supabase-ca.crt` (gitignored).
3. Generate two long random passwords (password manager). The password given in the original spec
   is too weak for an internet-facing database; use it only for a local DB.
4. Write them into `F:\data-analyst-astra\.env`:
   ```
   SUPABASE_PROJECT_REF=...        # 20-char ref only, not https://<ref>.supabase.co
   DATABASE_HOST=aws-1-ap-southeast-1.pooler.supabase.com   # aws-1, not aws-0
   DATABASE_PORT=5432
   DATABASE_NAME=postgres
   DATABASE_SSLMODE=verify-full
   DATABASE_SSLROOTCERT=secrets/supabase-ca.crt
   DATABASE_USER=astra_analyst
   DATABASE_PASSWORD=...
   REPORTING_DB_USER=astra_reporting
   REPORTING_DB_PASSWORD=...
   ```
5. Claude has written `sql/migrations/*.sql` (see [30-database-schema.md](30-database-schema.md)) and
   applies them through the Supabase connector after you approve. Role passwords are set by you in the
   SQL editor (`ALTER ROLE astra_analyst PASSWORD '...'`) so they never pass through chat.
6. Free tier note: the project pauses after ~7 days without activity. Open the dashboard or run
   the pipeline weekly, or upgrade.

- [x] H1 done (2026-11-17, verified with `.\astra check-db`, verify-full)

## H2 — Approve tool installs (Phase 2) — 2 min

Claude will review README, LICENSE and install scripts of `farisradifana/codegraph` and
`farisradifana/graphify` first and report findings. Then you reply "approve installs" or
reject specific ones. Also approve the Python packages: `psycopg[binary]`, `pandera`, `pytest`.

- [ ] H2 done

## H3 — Telegram bot credentials (blocks Phase 7, 9B) — ~10 min

1. In Telegram open **@BotFather** → `/mybots` → pick your Radifan bot → **API Token**.
   (No bot yet? `/newbot`.)
2. Add the bot to the target group as **admin** with "Post messages" (and "Manage topics" not required).
3. Group privacy: BotFather → bot → Bot Settings → Group Privacy → **Turn off** only if the bot
   must read normal group messages. For alerts only, leave it on.
4. Find IDs. A private-group link `https://t.me/c/<internal_id>/<topic_id>` usually maps to chat
   ID `-100<internal_id>` and thread ID `<topic_id>`, but treat that as an inference. Verify: post
   any message in that topic, then open in your browser (replace `<TOKEN>`):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   Read `message.chat.id` and `message.message_thread_id`.
5. Write in `F:\data-analyst-astra\.env`:
   ```
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   TELEGRAM_MESSAGE_THREAD_ID=...
   TELEGRAM_ALLOWED_USER_IDS=...   # your numeric Telegram user ID, comma-separated
   ```
   Your user ID: message **@userinfobot**.
6. Tell Claude whether test alerts may go into that group, or give a private test chat ID first.
7. Check, then send one test message (only after you agree it may go to that chat):
   ```powershell
   .\astra notify check --online
   ```
   ```powershell
   .\astra notify test
   ```
   `check --online` sends no message. See [32-telegram-alerts.md](32-telegram-alerts.md).

- [x] H3 done (2026-11-18: token, chat and topic set; `.\astra notify test` delivered)

## H4 — Gemini + n8n credentials (Phase 9) — ~10 min

1. Get/confirm a Gemini API key at https://aistudio.google.com/app/apikey. Check the billing
   tier you accept (free tier has rate limits; paid needs your approval).
2. Put `LLM_MODEL=...` (e.g. a current Gemini Flash model id) and `LLM_MODEL_KEY=...` in `.env`.
   Names are provider-neutral on purpose: Gemini is the first provider, another LLM can replace it
   later by changing these two values and the n8n Chat Model node.
3. n8n already has a credential named "Google Gemini(PaLM) Api account". Confirm it is the key
   to use, or create a new one: n8n → Credentials → New → Google Gemini(PaLM) API.
4. `N8N_ENCRYPTION_KEY`: leave it **empty** in `.env`. Checked 2026-11-17: n8n already keeps a key in
   `%USERPROFILE%\.n8n\config`. Back that file up in your password manager; losing it makes stored n8n
   credentials unreadable. Setting a different value makes n8n refuse to start.
5. After H1, create the n8n Postgres credential yourself (n8n → Credentials → Postgres) with the
   **read-only** `astra_reporting` user: host `aws-1-ap-southeast-1.pooler.supabase.com`, port `5432`,
   database `postgres`, user `astra_reporting.<project_ref>`, SSL required.
   Name it exactly `Astra reporting (read-only)`: the data assistant workflow refers to it by that name.
   Set SSL to **Require** and keep "Ignore SSL Issues (Insecure)" **off**. n8n 2.35.7 has no CA upload field, so
   start n8n with `.\astra n8n-start` (step 7), which trusts the Supabase CA.
6. `LLM_MODEL` must be a plain Gemini id, for example `gemini-2.5-flash`, not `provider/model`.
   Then run `.\astra n8n build` and import `n8n\build\astra_data_assistant.json` (doc 35, "Install in n8n").
7. Start n8n when needed, from the project folder (PowerShell or cmd). Stop any other n8n first:
   two n8n processes must not share the same `%USERPROFILE%\.n8n` data folder.
   ```powershell
   .\astra n8n-start
   ```
   The editor opens at http://127.0.0.1:5698 (this PC only). Keep the window open; Ctrl+C stops n8n.

- [ ] H4 done

## H5 — Looker Studio connectivity decision (Phase 8)

Looker Studio runs in Google's cloud. It cannot reach `localhost:5432`. Pick one:

| Option | Security | Cost | Effort |
|---|---|---|---|
| A. Managed cloud Postgres (e.g. Cloud SQL / Neon / Supabase) as a replica of `dataset`, SSL on, Google IP allow-list, read-only user | good | free tier–low | medium |
| B. Export clean CSVs to Google Sheets / BigQuery on schedule, Looker Studio reads that | good, no DB exposure | free | low |
| C. Expose local Postgres with port-forward + SSL + IP allow-list | risky on a home/office PC | free | medium, **not recommended** |

**Decided 2026-11-17: option A with Supabase.** After Phase 6 loads data:
https://lookerstudio.google.com → Create → Data source → PostgreSQL → host/port from the Session
pooler, database `postgres`, user `astra_reporting.<project_ref>`, its password, tick
**Enable SSL** and upload `supabase-ca.crt`. Sign in with your own Google account; Claude cannot
log in for you. Do not share the data source with "Anyone with link" editing rights.

Then build the report from [doc 34](34-looker-studio-dashboards.md):
1. Add one data source per `v_*` view listed there (schema `dataset`).
2. Build the 8 pages with the KPI formulas and filters from doc 34.
3. Set the date range to 2025 and compare each scorecard with the "2025 reference" column.
   A different number means a filter or an aggregation is wrong.
4. Share as Viewer with named people only.

- [ ] H5 done

## H6 — Approve scheduled job (Phase 10)

The daily job is ready (doc 33). It creates the Task Scheduler entry "Astra Daily ETL" for your user,
daily at 02:00, and runs only while you are signed in. Choose the time, then run it yourself or reply
"approve schedule":
```powershell
.\astra schedule -At 02:00
```
```powershell
.\astra schedule -Show
```
To remove it: `.\astra schedule -Unregister`.

- [x] H6 done (2026-11-18: registered daily at 08:30 WIB, user's choice; first run 2026-11-19 08:30)

## H7 — GitHub backup scope

Backup target: `https://github.com/farisradifana/ai-data-analyst-astra`.
Excluded from Git by `.gitignore`: `raw-data/`, `data/processed/`, `data/quarantine/`, `.env`,
logs, DB dumps, `secrets/`, model weights. Reason: spec forbids committing raw customer records and secrets.
**Decided 2026-11-17: repo stays public (prototype).** Consequence: no chat IDs, thread IDs, bot
tokens, project refs or passwords are written in any committed file; they live in `.env` only.

- [x] H7 done

## H8 — Navicat check (after H1)

New Connection → PostgreSQL → Host = Session pooler host, Port `5432`, Initial DB `postgres`,
User `astra_analyst.<project_ref>`, password from your `.env`. SSL tab → Use SSL, CA cert =
`secrets\supabase-ca.crt`, verify server. Test Connection → you should see schema `dataset`.

- [ ] H8 done

## Open data decisions (reply with "accept defaults" or your choice)

| ID | Question | Proposed default |
|---|---|---|
| D1 | Date `NN/NN/YYYY` = day-first, `NN-NN-YYYY` = month-first? | Yes; any value that fails this rule is quarantined as `INVALID_DATE_FORMAT` |
| D2 | `NET30`, `NET 30`, `30 DAYS` all mean Net 30? | Yes, map to `NET30`; original kept in audit |
| D3 | Sales quantity ≤ 0 or words (`two`)? | Quarantine (`INVALID_NUMERIC_VALUE`); no word-to-number guessing |
| D4 | Negative expense amount / list price? | Quarantine (`BUSINESS_RULE_VIOLATION`); not treated as refunds |
| D5 | Exact duplicate rows (700)? | Keep first occurrence, log others as `DUPLICATE_PRIMARY_KEY` in reconciliation |
| D6 | Blank `employees.manager_id` (19)? | Allowed (top of hierarchy), not rejected |
