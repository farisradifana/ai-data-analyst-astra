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

- [x] H2 done (2026-11-18): CodeGraph and Graphify **rejected** by the user, not installed. Python packages
  come from `requirements.txt` and `requirements-laya.txt`.

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
7. Start the Astra n8n when needed, from the project folder (PowerShell or cmd):
   ```powershell
   .\astra n8n-start
   ```
   - The editor opens at http://astra.localhost:5698 (this PC only). Keep the window open; Ctrl+C stops it.
   - Use that address, not `127.0.0.1:5698`. Browser cookies ignore the port, so on `127.0.0.1` the other n8n
     instances overwrite this one's login cookie and saving fails with "Unauthorized".
   - The launcher sets `N8N_SECURE_COOKIE=false`. Without it n8n shows "configured to use a secure cookie" on
     `astra.localhost` (plain HTTP). This is acceptable only because n8n listens on 127.0.0.1. Restart n8n after updating.
   - It is a separate n8n with its own data folder `%USERPROFILE%\.n8n-astra`, so it runs next to your
     other n8n instances (5678 / 5688). Its task runner uses port 5699.
   - First start: create the n8n owner account, then create the two credentials (steps 3 and 5) in **this**
     instance. Credentials from the other n8n are not visible here.
   - Back up `%USERPROFILE%\.n8n-astra\.n8n\config` in your password manager: it holds the key that encrypts
     this instance's credentials.

- [x] H4 done (2026-11-18: credentials in the Astra n8n, workflow imported, chat answered 2025 net revenue
  correctly with `gemini-3.5-flash`. Keep `LLM_MODEL` in `.env` on that id so `.\astra n8n build` matches.)

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
1. Add one data source per `v_*` view listed there. The table list after sign-in is empty, because Looker Studio
   lists only the `public` schema. Choose **CUSTOM QUERY** instead of TABLE and enter
   `SELECT * FROM dataset.<view>`, for example `SELECT * FROM dataset.v_sales_daily`.
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

## H9 — Telegram chat for the data assistant (doc 36) — ~15 min

Go-ahead given 2026-11-18. Design: local bridge, outbound only, no public webhook ([doc 36](36-telegram-assistant.md)).
The alert bot already sends its messages to another service's webhook. Leave that alone and create a new bot.

1. In Telegram, open **@BotFather** → `/newbot` → choose a name and a username ending in `bot`. Copy the token
   into `.env` as `TELEGRAM_ASSISTANT_BOT_TOKEN=`. Claude cannot create the bot or see the token.
2. `TELEGRAM_ALLOWED_USER_IDS` is already set in `.env` (format checked). Keep only the user ids that may ask.
3. Make a webhook token in PowerShell. It prints 64 random characters:
   ```powershell
   $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ($b | ForEach-Object { $_.ToString('x2') }) -join ''
   ```
   Put it in `.env` as `ASTRA_ASSISTANT_WEBHOOK_TOKEN=`.
4. Start n8n with `.\astra n8n-start` and open http://astra.localhost:5698. Go to Credentials → New → **Header Auth**.
   Name the credential `Astra assistant webhook token`. Header name `X-Astra-Token`, value = the same token. Save.
5. Build, then import the workflow:
   ```powershell
   .\astra n8n build
   ```
   In n8n: Workflows → Import from file → `n8n\build\astra_telegram_assistant.json`. Open the Webhook node:
   its credential must show `Astra assistant webhook token`. The Gemini and Postgres nodes use the same
   credentials as `ASTRA_DATA_ASSISTANT`. Save, then **Activate** (Publish) the workflow.
6. Check the settings (sends no message):
   ```powershell
   .\astra telegram-bot check --online
   ```
   You want `config OK` and `Telegram webhook not set`.
7. Start the bridge and leave the window open. Ctrl+C stops it:
   ```powershell
   .\astra telegram-bot run
   ```
8. In a private chat with the new bot, ask `Berapa net revenue 2025?`. The expected answer is Rp 54.269.362.661.171.
   Optional (spec case 16): from an account that is not on the list, you should get "Not authorized for this bot.".
   For the group: add the new bot to the group and use `/ask <question>`. To ask by tagging the bot
   (`@yourbot Berapa net revenue 2025?`) or by replying to its answer, also turn privacy mode off:
   @BotFather → `/setprivacy` → choose the new bot → **Disable**. Then remove the bot from the group and add it
   again: Telegram applies the privacy change to a group only when the bot rejoins it.

Tell Claude the result. The answer is enough; do not paste tokens or ids.

- [x] H9 done (2026-11-18: question in Telegram answered through the bridge)

Do not set a webhook on the assistant bot (for example with a Cloudflare tunnel). The bridge needs none and stops
if one is set. If a question gets "not available" and the bridge logs `webhook HTTP 404`, the workflow is not
published: open `ASTRA_TELEGRAM_ASSISTANT` in n8n and click Publish.

## H10 — Laya route hint in n8n and Telegram (doc 37) — ~15 min

Requested 2026-11-18. `LAYA_API_TOKEN` is already set in `.env` (checked: present, long enough).

1. Start the Laya API in its own window and leave it open. Wait for the line `laya api ready` (about 30 s):
   ```powershell
   .\astra laya-api
   ```
2. In n8n (http://astra.localhost:5698): Credentials → New → **Header Auth**. Name the credential
   `Laya API token`. Header name `Authorization`. Value: the word `Bearer`, one space, then the value of
   `LAYA_API_TOKEN` from `.env`. Save.
3. The gateway has its own token. Make one with the H9 step 3 command, put it in `.env` as
   `ASTRA_LAYA_GATEWAY_TOKEN=`, then in n8n: Credentials → New → **Header Auth**, credential name
   `Astra Laya gateway token`, header name `X-Astra-Token`, value = that token. Save.
4. Build the workflows:
   ```powershell
   .\astra n8n build
   ```
   Import `n8n\build\astra_laya_decision_engine.json`. The Webhook node uses `Astra Laya gateway token`,
   the `Laya predict` node uses `Laya API token`. Save, then **Publish**.
5. Replace the Telegram workflow. n8n allows only one published workflow per webhook path, so:
   open the current `ASTRA_TELEGRAM_ASSISTANT` → Unpublish → ⋮ → Archive. Then import
   `n8n\build\astra_telegram_assistant.json`. Check the credentials: Webhook uses
   `Astra assistant webhook token`, `Route hint (Laya)` uses `Astra Laya gateway token`, the model uses Gemini,
   the tools use `Astra reporting (read-only)`.
   Save, then **Publish**.
6. Keep the bridge running (`.\astra telegram-bot run`) and ask the bot `Berapa net revenue 2025?`.
   The answer is still Rp 54.269.362.661.171. In n8n → Executions, the Telegram execution shows the
   `Route hint (Laya)` result.
7. Optional: stop the Laya API (Ctrl+C) and ask again. The bot must still answer (hint `UNAVAILABLE`).
   Tell Claude whether Ctrl+C stopped the API cleanly: that is an open check in doc 26.

Tell Claude the result. Claude can then test the gateway directly without printing any token.

- [x] H10 done (2026-11-18): steps 1–5 done by the user; the Laya API runs under the background supervisor.
  Checked 2026-11-18: Laya `/health` 200 on 127.0.0.1:8765; gateway `/webhook/astra-laya` is published
  (403 without the token). The full answer check with the token (step 6) was skipped by the user's decision.

## Open data decisions (reply with "accept defaults" or your choice)

| ID | Question | Proposed default |
|---|---|---|
| D1 | Date `NN/NN/YYYY` = day-first, `NN-NN-YYYY` = month-first? | Yes; any value that fails this rule is quarantined as `INVALID_DATE_FORMAT` |
| D2 | `NET30`, `NET 30`, `30 DAYS` all mean Net 30? | Yes, map to `NET30`; original kept in audit |
| D3 | Sales quantity ≤ 0 or words (`two`)? | Quarantine (`INVALID_NUMERIC_VALUE`); no word-to-number guessing |
| D4 | Negative expense amount / list price? | Quarantine (`BUSINESS_RULE_VIOLATION`); not treated as refunds |
| D5 | Exact duplicate rows (700)? | Keep first occurrence; drop the others as `EXACT_DUPLICATE_ROW` (counted in reconciliation). Same key with different values → quarantined as `DUPLICATE_PRIMARY_KEY` |
| D6 | Blank `employees.manager_id` (19)? | Allowed (top of hierarchy), not rejected |
