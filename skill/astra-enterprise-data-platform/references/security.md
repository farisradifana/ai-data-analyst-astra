# Security requirements

## Secrets and identifiers

- Secrets live in an untracked `.env` (template `.env.example` with names only) or in the tool's own credential store
  (n8n credentials, Windows Task Scheduler user context). Certificates in a gitignored `secrets/` folder.
- Never print, log, echo or commit: passwords, API keys, bot tokens, `.env` values. Do not read `.env` through the shell;
  load it in code.
- In a **public** repo also keep out: database project refs, Telegram chat/thread/user ids, private emails.
  Scan every staged diff before committing, e.g. for the project ref, `bot\d+:`, `-100\d{6,}` and email patterns.
- If a secret leaks, stop, tell the user and recommend rotation. A history rewrite is not enough.

## Access

- Least privilege: writer role for the ETL only; read-only reporting role for dashboards and the AI agent; PII
  columns denied to reporting.
- Every consumer connects with TLS and certificate verification (`verify-full`).
- Services bind to loopback: n8n `127.0.0.1`, local APIs `127.0.0.1` with a bearer token. No port exposure, tunnel
  or public webhook without the user's approved design.
- Insecure switches (e.g. n8n `N8N_SECURE_COOKIE=false`) only on loopback-only instances, with a comment saying why.

## Data

- Never commit raw records, processed data, quarantine exports or DB dumps (`raw-data/`, `data/`, `*.dump` ignored).
- Alerts and logs carry counts and codes, never values.
- The AI agent can only run approved, parameterized read queries.

## Ask the user first

Destructive SQL, production migrations, grant/RLS/role changes, replacing a database, changing credentials, sending a
Telegram message, enabling paid services, exposing ports, force-push or history rewrite, deleting data or branches.
Passwords and API keys are typed by the user, never by the assistant.
