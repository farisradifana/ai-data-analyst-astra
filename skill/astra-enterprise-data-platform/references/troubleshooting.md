# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Connection timeout / IPv6 error to `db.<ref>.supabase.co` | Direct host is IPv6 only | Use the Session pooler host (`aws-N-<region>.pooler.supabase.com`), port 5432; copy the exact `aws-N` from the dashboard |
| `prepared statement ... does not exist` | Transaction pooler (port 6543) | Use the Session pooler, port 5432 |
| `tenant or user not found` | User without the `.<project_ref>` suffix | User `<role>.<project_ref>` |
| `self-signed certificate in certificate chain` | CA not trusted | psycopg2: `sslrootcert` = downloaded CA; n8n: `NODE_EXTRA_CA_CERTS` pointing to the CA (its Postgres credential has no CA field) |
| Database unreachable after a quiet week | Supabase free tier paused | Resume in the dashboard; run the pipeline weekly |
| n8n "Problem creating credential: Unauthorized" | Several n8n instances on 127.0.0.1 share the `n8n-auth` cookie (cookies ignore the port) | Open the instance on its own `*.localhost` name |
| n8n page "configured to use a secure cookie" | Plain HTTP on a hostname other than `localhost` | `N8N_SECURE_COOKIE=false`, only while n8n listens on 127.0.0.1 |
| n8n starts on 5678 with the default folder from a `.cmd` launcher | `n8n` is a batch shim; without `call` the launcher's environment is lost | `call n8n start` |
| n8n "port 5679 in use" on start | Task runner broker port shared with another instance | Set `N8N_RUNNERS_BROKER_PORT` to a free port |
| Chat answers in 0.3 s with "resource could not be found" | Model id not available for this key | Pick a model listed for the key in Google AI Studio |
| Chat hangs for minutes | Rate limit (429) retried silently | Check quota; wait; switch to a model with quota |
| `LLM_MODEL` rejected at build | Value is `provider/model` or has spaces | Plain model id |
| `.cmd` launcher behaves oddly after an edit | File saved with LF line endings | Rewrite with CRLF; check an unknown command still exits 2 |
| ETL stops: "changed after it was loaded" | A registered source file was edited | Restore it; put new data in a new file under `raw-data/<table>/` |
| Daily files ignored | Named `raw-data/<table>_<date>.csv` | Only `raw-data/<table>.csv` and `raw-data/<table>/*.csv` are read |
| Quarantine row never graduates | Its parent is still in quarantine (`depends_on`) or the edit is still invalid | Fix the parent; `.\astra fix show` the row for its new label |
| ETL "another ETL run is in progress" | Advisory lock held by a running or hung session | Wait for the run; a closed connection releases the lock |
| `etl_run` row stuck in RUNNING | Process killed mid-load | Transaction rolled back; mark the run row FAILED after checking nothing else runs |
