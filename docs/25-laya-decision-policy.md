# 25 — Laya Confidence and Decision Policy

## Confidence field used

laya 0.4.35 returns two numbers per `choice` answer:

- `answer_confidence` = highest option probability. **Used for gating** (upstream recommendation).
- `confidence` = 1 − normalised entropy. Logged in evaluation output only.

Neither number is a calibrated probability of being correct. Thresholds come only from the
labeled evaluation ([27-laya-evaluation.md](27-laya-evaluation.md)).

## Bands and actions (`src/decision_engine/confidence_policy.py`)

| Band | Condition | Action when task enabled | Action when task disabled |
|---|---|---|---|
| HIGH | `conf >= high` | ACCEPT (low-risk routing only) | REVIEW |
| MEDIUM | `medium <= conf < high` | REVIEW | REVIEW |
| LOW | `conf < medium` | FALLBACK to `fallback.py` rules | FALLBACK |
| error | inference exception or label outside the closed set | rule fallback, action REVIEW, error recorded | same |

Thresholds live in `config/laya_policy.json`. If the file is missing, both tasks are disabled and
nothing is auto-accepted (unit test `test_missing_policy_file_is_conservative`).

## What is logged per decision

`request_id`, `run_id`, `task`, `label`, `confidence`, `band`, `action`, `source`
(`laya`/`rule_fallback`), `checkpoint`, `latency_ms`, `fallback_used`, `error`.
The input text is not logged, because incident descriptions can contain record details.

## Never automated

Approving financial transactions, deleting or altering records or source files,
employment-related decisions, accusing a person or supplier of fraud.
