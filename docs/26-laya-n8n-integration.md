# 26 — Laya Local API and n8n Integration

Status 2026-11-17: the local API is **implemented and smoke-tested**. The n8n workflow is
**not built yet**. No existing n8n workflow was modified. n8n 2.35.7 runs natively on Windows
(not Docker), so `127.0.0.1` from n8n reaches the host.

## Local API (`src/decision_engine/api.py`)

Start (from project root):
```bash
PYTHONPATH=src HF_HUB_OFFLINE=1 .venv-laya/Scripts/python -m decision_engine.api
```
Needs `LAYA_API_TOKEN` (≥ 16 chars) in the environment. Without it, the server refuses to start.
Generate one with `python -c "import secrets;print(secrets.token_urlsafe(32))"` and keep it in `.env`.

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | none | `{"status": "loading" / "ready" / "error"}` |
| `GET /model-info` | Bearer | package version, checkpoint, pinned revision, `hosted_api: false`, current policy |
| `POST /predict` | Bearer | body `{"task": "agent_route" or "dq_category", "text": "...", "request_id"?, "run_id"?}` → `Decision` |
| `POST /evaluate` | Bearer | body `{"items": [{"task","text","label"}]}` (max 50) → accuracy and per-item results |

Controls:
- Binds `LAYA_API_HOST` (default `127.0.0.1`), port `LAYA_API_PORT` (default `8765`). A
  non-loopback host is refused unless `LAYA_API_ALLOW_REMOTE=1`, which needs a separately
  reviewed network design.
- Bearer token compared in constant time (`hmac.compare_digest`).
- Closed task names; text 1–2,000 chars (422 otherwise); body > 64 KB → 413.
- Model loaded once at startup; one inference at a time; `LAYA_API_TIMEOUT_S` (default 30) → 504.
- `/docs` and `/openapi.json` disabled.
- Responses and logs never contain the input text or the token.

Known limits:
- After a 504 timeout the torch thread keeps running until it finishes. The next request can
  then overlap it briefly.
- Graceful shutdown through Ctrl+C is not yet verified on Windows. The smoke test stopped the
  process by termination.

### Smoke test, 2026-11-17 (real multilingual model, offline)

| Check | Result |
|---|---|
| `/health` after startup | `ready` |
| `/predict` without token | 401 |
| `/predict` task `run_sql` | 422 |
| Listening socket | `127.0.0.1:8765` only |
| Token in log file | not found |
| "Berapa total revenue bulan ini?" | `UNKNOWN` 0.74 MEDIUM → REVIEW (**wrong label**, see doc 27) |
| "Kenapa transaksi ini ditolak?" | `DATA_QUALITY` 0.61 MEDIUM → REVIEW |
| "Tolong proses ulang data penjualan yang ditolak kemarin." | `REPROCESSING_REQUEST` 0.81 HIGH → REVIEW (task disabled) |
| Warm latency | 1.2–1.9 s |

Automated tests: `tests/decision_engine/test_api.py` (20 tests, stub model).

## Planned workflow `ASTRA_LAYA_DECISION_ENGINE` (not built)

Trigger → Validate Input → HTTP Request `POST http://127.0.0.1:8765/predict` with header
`Authorization: Bearer {{$env.LAYA_API_TOKEN}}` (or an n8n Header Auth credential) → Parse
Decision → Switch on `action` (`ACCEPT` → mapped workflow, `REVIEW` → review queue / ask user
to confirm, `FALLBACK` → rule label) → Log → Telegram summary alert (counts only).

Separate workflows planned: Data Quality Classification, AI Agent Request Routing, Operational
Alert Classification. The LLM (`LLM_MODEL`, Gemini first) stays a separate node.

While `enabled: false` in `config/laya_policy.json`, n8n treats Laya output as a hint only.
