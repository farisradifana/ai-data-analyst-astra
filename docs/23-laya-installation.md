# 23 — Laya Installation (verified 2026-11-17)

Isolated venv: `F:\data-analyst-astra\.venv-laya` (gitignored). System Python 3.12.1 and other
project venvs were not modified.

## Steps actually run

```powershell
python -m venv .venv-laya
```
```powershell
.venv-laya\Scripts\python -m pip install --index-url https://download.pytorch.org/whl/cpu torch
```
```powershell
.venv-laya\Scripts\python -m pip install "laya==0.4.35" pytest
```

CPU-only torch was installed on purpose: the machine has no NVIDIA GPU (AMD Radeon RX 560X /
Vega 8), so CUDA wheels would only waste disk. Install log: `logs/laya_install.log` (gitignored).

## Resulting versions

| Package | Version |
|---|---|
| laya | 0.4.35 (PyPI, source repo NandhaKishorM/laya, Apache-2.0) |
| torch | 2.15.0+cpu |
| transformers | 5.23.0 |
| huggingface_hub | 2.4.0 |
| vegaml | 0.16.3 (installed as a laya dependency; vega lane disabled in code) |
| pytest | 9.2.0 |
| fastapi / starlette | 0.163.1 / 1.10.0 (added 2026-11-17, user-approved) |
| uvicorn | 0.54.0 |
| httpx | 0.28.1 (FastAPI TestClient) |

## Model weights

- Downloaded once from Hugging Face on first use into `%USERPROFILE%\.cache\huggingface\hub`.
- Revisions pinned by the package (`laya.PINNED_REVISIONS`):
  - `convaiinnovations/laya` → `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`
  - `convaiinnovations/laya-multilingual` → `e4e9ddf21a7b1903b7acffd8814ad4307bf63a67`
  - `convaiinnovations/laya-typed-decisions` → `1a793eb568e6718f15941d08f85432581df534e3`
- After download set `HF_HUB_OFFLINE=1` to forbid network access during inference.
- Windows without Developer Mode cannot create symlinks, so the HF cache stores full copies
  (warning is harmless; silence with `HF_HUB_DISABLE_SYMLINKS_WARNING=1`).

## Outbound-network check

The installed `laya` and `vegaml` sources were searched for URLs. Only Hugging Face, GitHub and
PyTorch documentation links were found; no hosted inference endpoint is called.

## Verify

Unit tests (no weights needed):
```powershell
.\astra test
```
Real local inference, offline (needs cached weights):
```powershell
.\astra laya-test
```
Result 2026-11-17: 44 unit/API passed; 5 real-model passed offline.
