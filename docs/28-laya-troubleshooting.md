# 28 — Laya Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `huggingface_hub ... does not support symlinks` warning | Windows without Developer Mode | Harmless. Set `HF_HUB_DISABLE_SYMLINKS_WARNING=1`, or enable Developer Mode to save disk |
| `laya.load()` / Router hangs at import | transformers probing TensorFlow | `USE_TF=0` (set automatically by `model_manager.py`) |
| First prediction takes minutes | weight download (~650 MB multilingual, ~800 MB others) and cold load | Wait once; later loads use the cache (35 s multilingual) |
| Out-of-memory / system freeze | two checkpoints resident, or little free RAM | Keep `max_loaded=1`; close other apps; use multilingual |
| Slow inference | too many or too few torch threads | `LAYA_THREADS` ≤ physical cores (4 here) |
| Decision has `source=rule_fallback`, `error` set | inference raised or returned a label outside the closed set | Check `logs/`; engine already fell back and marked REVIEW |
| Everything goes to REVIEW | `config/laya_policy.json` has `enabled: false` (intended) | Enable only after the criteria in doc 27 are met |
| Network calls at load | HF hub checks revisions online | After download set `HF_HUB_OFFLINE=1` (verified 2026-11-17: `pytest -m laya` passes offline) |
