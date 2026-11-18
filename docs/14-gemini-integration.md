# 14 — Gemini integration

Last checked: 2026-11-18

How Google Gemini is used. Workflow details are in [doc 13](13-n8n-ai-agent.md) and [doc 35](35-n8n-data-assistant.md).

## Where Gemini is used

Only in the n8n workflow `ASTRA_DATA_ASSISTANT`, through n8n's Google Gemini chat model node.
No Python code in this repo calls Gemini or any LLM API. The Laya decision engine is local and uses no LLM API ([doc 22](22-laya-architecture.md)).

## Settings

| Name | Purpose | Read by |
|---|---|---|
| `LLM_MODEL` | Gemini model id. Written into the model node by `.\astra n8n build` | `src/astra_n8n/__main__.py` (through `load_env`) |
| `LLM_MODEL_KEY` | Reserved for the API key (provider-neutral name) | No code reads it. The key lives in an n8n credential |

Model id handling (`model_name` in `src/astra_n8n/assistant.py`):
- Empty value: the node gets the placeholder `SET_LLM_MODEL`, and `build` prints a warning.
- `gemini-3.5-flash` becomes `models/gemini-3.5-flash`. A value that already starts with `models/` is kept.
- Allowed characters: letters, digits, `.`, `_`, `-`; length 3–80. Anything else is rejected, for example `provider/model` or a value with spaces.
  The error names the offending characters, never the whole value.

## Credential handling

- The Gemini API key is stored as an n8n credential named `Google Gemini(PaLM) Api account` (type `googlePalmApi`) in the Astra n8n.
  n8n encrypts it with the key in `%USERPROFILE%\.n8n-astra\.n8n\config`.
- The generated workflow JSON holds the credential name only. Tests check that no credential id or secret is in it.
- Do not paste the key in chat, docs, commits or logs. `.env` is untracked.

## Lessons from the live setup (2026-11-18)

| Model id | Result |
|---|---|
| `gemini-3.6-flash` | Failed: "resource ... could not be found". This key has no access to that model |
| `gemini-3.8-flash` | Failed: "too many requests" (rate limit). n8n retried quietly, so the chat looked frozen for about 3 minutes |
| `gemini-3.5-flash` | Works. Answered the 2025 net revenue question in about 80 s end to end |

- If the chat hangs, check the model's quota in Google AI Studio first.
- If you get "could not be found", pick a model your key can use.
- Keep `LLM_MODEL` in `.env` on the working id so `.\astra n8n build` matches the imported workflow.

## Cost

- The free tier has rate limits. A paid tier needs the user's approval before use ([HUMAN-STEPS.md](HUMAN-STEPS.md), H4).
- Each question can run several model calls (up to 8 agent iterations) plus tool calls. No usage metering is built.
- No cost figure was measured for this project.

## What data reaches Gemini

Gemini sees:
- the user's question and the last 10 messages of the chat session;
- the fixed system prompt;
- tool results: aggregated rows from `dataset.v_*` views (sums, counts, rates by date, branch, category, department).

Gemini does not see names, emails, phones, salaries or single records. The `astra_reporting` role cannot read those columns ([doc 30](30-database-schema.md)),
and the views are aggregated. `v_customers_public` has no PII columns.
The data-quality tool returns counts per table and rule only.
The data is SYNTHETIC, but treat the path as if it were real: aggregates leave the PC and go to Google.
Also, the system prompt tells the model to treat tool results as data, not instructions.
