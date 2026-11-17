# 29 — Laya Cost and Resource Usage

## Cost

- Zero per-request fees: open weights (Apache-2.0) run locally on CPU.
- No API key, no hosted Laya service, no OpenRouter or gateway, no Studio/vegaml credits used
  (vega lane disabled in `model_manager.py`).
- Only network use: one-time weight download from Hugging Face. With `HF_HUB_OFFLINE=1` the
  real-model tests (`pytest -m laya`) passed with no network access (2026-11-17).

## Measured on this machine (2026-11-17)

| Item | Value |
|---|---|
| CPU | AMD Ryzen 5 3550H, 4 cores / 8 threads, no NVIDIA GPU |
| RAM | 13.9 GB total; only ~1–1.7 GB free during tests (other apps running) |
| Disk: venv | ~1 GB (`.venv-laya`, CPU torch) |
| Disk: HF cache, 3 checkpoints | 1.9 GB (`%USERPROFILE%\.cache\huggingface\hub`, no symlinks) |
| multilingual load (cached) | 35 s |
| multilingual latency per choice question | p50 0.98–1.16 s, p95 1.11–1.38 s |
| english / typed-decisions latency | p50 2.7–3.5 s |
| Peak process RAM, multilingual | ~2.2 GB |

Keep `max_loaded=1` (already set). Loading two checkpoints at once would need ~4–5 GB.
