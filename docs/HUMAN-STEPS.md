# Human Steps Guide

Steps only a person can do (installs needing admin rights, secrets, external accounts, approvals).
Do them in order. Never paste a password, token or API key into chat — put them in the
untracked `F:\data-analyst-astra\.env` file yourself. Mark each box when done.

---

## H1 — Install PostgreSQL (blocks Phase 6) — ~15 min

1. Download the Windows installer for PostgreSQL 17 from https://www.postgresql.org/download/windows/
   (EDB installer).
2. Run it as administrator. Keep the defaults:
   - Components: PostgreSQL Server, pgAdmin 4, Command Line Tools (Stack Builder not needed).
   - Port: `5432`. Locale: default.
   - Set a strong password for the `postgres` superuser. Store it in your password manager.
     **Do not** reuse `astradata-analyst`.
3. Add `C:\Program Files\PostgreSQL\17\bin` to your user PATH, then open a new terminal and run:
   ```bash
   psql --version
   ```
4. Confirm it listens only locally. In `C:\Program Files\PostgreSQL\17\data\postgresql.conf`
   `listen_addresses` should be `'localhost'` (default). Do not change it to `'*'`.
5. Tell Claude "PostgreSQL installed". Claude then creates `astra_analytics`, role
   `astra_analyst`, schema `dataset`, and a read-only `astra_reporting` role via scripts.
   You run the one superuser step yourself, because it needs the `postgres` password:
   ```bash
   psql -U postgres -h localhost -f sql/000_bootstrap_superuser.sql
   ```
   (Claude will create this file; review it before running.)

- [ ] H1 done

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
4. Find IDs. The link `https://t.me/c/3979255139/2332` suggests chat ID `-1003979255139` and
   topic (thread) ID `2332`, but this is an inference. Verify: post any message in that topic,
   then open in your browser (replace `<TOKEN>`):
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

- [ ] H3 done

## H4 — Gemini + n8n credentials (Phase 9) — ~10 min

1. Get/confirm a Gemini API key at https://aistudio.google.com/app/apikey. Check the billing
   tier you accept (free tier has rate limits; paid needs your approval).
2. Put `GEMINI_API_KEY=...` and `GEMINI_MODEL=...` (e.g. a current Gemini Flash model) in `.env`.
3. n8n already has a credential named "Google Gemini(PaLM) Api account". Confirm it is the key
   to use, or create a new one: n8n → Credentials → New → Google Gemini(PaLM) API.
4. Set `N8N_ENCRYPTION_KEY` once (keep it in your password manager; losing it makes stored n8n
   credentials unreadable). If n8n has already generated one, it is in `%USERPROFILE%\.n8n\config` — keep that value.
5. After H1, create the n8n Postgres credential yourself (n8n → Credentials → Postgres) with the
   **read-only** `astra_reporting` user, host `localhost`, DB `astra_analytics`, SSL off for local.
6. Start n8n when needed:
   ```bash
   n8n start
   ```

- [ ] H4 done

## H5 — Looker Studio connectivity decision (Phase 8)

Looker Studio runs in Google's cloud. It cannot reach `localhost:5432`. Pick one:

| Option | Security | Cost | Effort |
|---|---|---|---|
| A. Managed cloud Postgres (e.g. Cloud SQL / Neon / Supabase) as a replica of `dataset`, SSL on, Google IP allow-list, read-only user | good | free tier–low | medium |
| B. Export clean CSVs to Google Sheets / BigQuery on schedule, Looker Studio reads that | good, no DB exposure | free | low |
| C. Expose local Postgres with port-forward + SSL + IP allow-list | risky on a home/office PC | free | medium, **not recommended** |

Reply with A, B or C. Then in https://lookerstudio.google.com: Create → Data source → PostgreSQL
(A) or Google Sheets/BigQuery (B); sign in with your own Google account. Claude cannot log in for you.

- [ ] H5 done

## H6 — Approve scheduled job (Phase 10)

Claude will propose a Windows Task Scheduler entry (e.g. daily 02:00 incremental run). Reply
"approve schedule" to create it.

- [ ] H6 done

## H7 — GitHub backup scope

Backup target: `https://github.com/farisradifana/ai-data-analyst-astra`.
Excluded from Git by `.gitignore`: `raw-data/`, `data/processed/`, `data/quarantine/`, `.env`,
logs, DB dumps. Reason: spec forbids committing raw customer records and secrets. If the repo is
**public**, confirm that is intended; private is recommended. Check: GitHub → repo → Settings → General → Danger Zone → visibility.

- [ ] H7 done

## H8 — Navicat check (after H1)

New Connection → PostgreSQL → Host `localhost`, Port `5432`, Initial DB `astra_analytics`,
User `astra_analyst`, password from your `.env`. Test Connection → you should see schema `dataset`.

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
