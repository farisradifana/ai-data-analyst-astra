# 27 — Laya Evaluation Results (run 2026-11-17)

Command:
```powershell
.\astra laya-eval --checkpoints multilingual english typed-decisions --threads 4
```
Raw outputs: `reports/laya/benchmark.json`, `reports/laya/benchmark.md`,
`reports/laya/eval_<checkpoint>_<task>.jsonl` (each row: input, expected, prediction, confidence,
correct flag, language, checkpoint, revision).

## Dataset

| Set | File | Items | Labels | Languages |
|---|---|---:|---:|---|
| Data quality incidents | `evals/laya/dq_incidents.jsonl` | 40 | 10 × 4 | 20 EN / 20 ID |
| Agent routing | `evals/laya/agent_routing.jsonl` | 32 | 8 × 4 | 16 EN / 16 ID |

Hand-written synthetic examples modelled on the profiled defects. **Too small for production
claims**: one item changes accuracy by 2.5–3 points.

## Results (CPU, AMD Ryzen 5 3550H, 4 threads)

| Checkpoint | Task | Acc | EN | ID | Macro F1 | ECE (5-bin) | p50 ms | Peak RSS MB* |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| multilingual | dq_category | 0.600 | 0.65 | 0.55 | 0.594 | 0.193 | 1,162 | 2,225 |
| multilingual | agent_route | 0.688 | 0.81 | 0.56 | 0.663 | 0.197 | 980 | 2,225 |
| english | dq_category | 0.575 | 0.70 | 0.45 | 0.536 | 0.095 | 2,708 | 3,018 |
| english | agent_route | 0.625 | 0.81 | 0.44 | 0.639 | 0.089 | 2,680 | 3,018 |
| typed-decisions | dq_category | 0.600 | 0.75 | 0.45 | 0.562 | 0.318 | 3,491 | 3,018 |
| typed-decisions | agent_route | 0.719 | 0.88 | 0.56 | 0.713 | 0.337 | 2,901 | 3,018 |

\* Peak working set of the benchmark process. Checkpoints ran one after another in one process,
so english and typed-decisions peaks are upper bounds.

Model load time (from local cache): multilingual 35 s, english 234 s, typed-decisions 236 s.
The first load after download took 240 s.

### Selective accuracy (multilingual)

| Gate `answer_confidence >=` | DQ coverage / acc | Routing coverage / acc |
|---|---|---|
| 0.5 | 0.85 / 0.68 | 0.81 / 0.73 |
| 0.7 | 0.68 / 0.78 | 0.59 / 0.79 |
| 0.8 | 0.60 / 0.83 | 0.56 / 0.83 |
| 0.9 | 0.53 / 0.86 | 0.31 / 0.80 |

typed-decisions confidences are low (mostly < 0.5), so a confidence gate would send almost
everything to review. english is better calibrated (lower ECE) but much weaker in Indonesian.

### Main confusions (multilingual)

- `KPI_QUERY` → `UNKNOWN` (3 of 4): includes the spec's example "Berapa total revenue bulan ini?".
- `INVALID_NUMERIC_VALUE` → `UNKNOWN_ERROR` (3).
- `MISSING_REQUIRED_FIELD` / `INCONSISTENT_CATEGORY` → `DUPLICATE_RECORD` (2 each).

### Rule fallback comparison — read with care

`fallback.py` scored 0.90 (DQ) and 1.00 (routing), but its keywords were written while looking
at this same set. That is overfitting, not evidence that rules beat the model. A fresh,
held-out set written by someone else is needed for a fair comparison.

## Decision

- Selected checkpoint: **multilingual** (`convaiinnovations/laya-multilingual` @
  `e4e9ddf21a7b1903b7acffd8814ad4307bf63a67`). Reasons: best Indonesian accuracy (tied), 2.5–3×
  faster, lowest RAM, 35 s load.
- **Automatic routing stays disabled** for both tasks (`config/laya_policy.json`,
  `enabled: false`). Every Laya label is a suggestion sent to review; LOW confidence uses rules.
- Not done: fine-tuning (needs approval), held-out test set, score/noul benchmarks.

## Re-enable criteria (proposal)

Enable a task only when, on a held-out set of at least 200 items per task (both languages):
accuracy at the chosen HIGH threshold ≥ 0.90 with coverage ≥ 0.50, and no single label
recall < 0.70.
