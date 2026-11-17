# 26 — Laya n8n Integration (DESIGN — not implemented yet)

Status 2026-11-17: nothing is built in n8n yet. No existing workflow was modified.
n8n 2.35.7 runs natively on Windows (not Docker), so `127.0.0.1` from n8n reaches the host.

## Planned local API (`src/decision_engine/api.py`, not yet written)

- FastAPI, bound to `127.0.0.1:${LAYA_API_PORT}`, header `Authorization: Bearer ${LAYA_API_TOKEN}`.
- `GET /health`, `GET /model-info`, `POST /predict` (`PredictRequest`), `POST /evaluate`.
- Model loaded once at startup; request timeout; 2,000-char input limit; structured logs.
- Needs `fastapi` + `uvicorn` in `.venv-laya` (approval pending).

## Planned workflow `ASTRA_LAYA_DECISION_ENGINE`

Trigger → Validate Input → HTTP Request (`/predict`) → Parse Decision → Switch on `action`
(`ACCEPT` → mapped workflow, `REVIEW` → review queue, `FALLBACK` → rule label) → Log →
Telegram summary alert (counts only).

Separate workflows planned: Data Quality Classification, AI Agent Request Routing, Operational
Alert Classification. LLM (`LLM_MODEL`, Gemini first) stays a separate node.

While `enabled: false` in `config/laya_policy.json`, n8n treats Laya output as a hint only and
routes with the rule label or asks the user to confirm.
