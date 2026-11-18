# ai-data-analyst-astra

SYNTHETIC enterprise data analytics simulation (Astra International Sunter Operations style).
Not affiliated with Astra International; no internal data or systems are used.

Stack: Python/pandas ETL → Supabase PostgreSQL (schema `dataset`) → Google Looker Studio,
plus an n8n AI agent (provider-neutral `LLM_MODEL` / `LLM_MODEL_KEY`, Gemini first), Telegram
alerts, and Laya, a local open-source decision engine (Apache-2.0, no API fees).

- Laya: [docs/22-laya-architecture.md](docs/22-laya-architecture.md) · evaluation
  [docs/27-laya-evaluation.md](docs/27-laya-evaluation.md). Laya credit: NandhaKishorM/laya and
  convaiinnovations/laya, licensed Apache-2.0.

- Start here: [docs/00-project-overview.md](docs/00-project-overview.md) (doc map for docs 00–35)
- Setup on a new PC: [docs/18-deployment-guide.md](docs/18-deployment-guide.md)
- Progress: [docs/STATUS.md](docs/STATUS.md)
- Steps that need a human: [docs/HUMAN-STEPS.md](docs/HUMAN-STEPS.md)
- Profiling report: [reports/profiling/profiling_summary.md](reports/profiling/profiling_summary.md)

Raw data (`raw-data/`) is intentionally not stored in Git.

## Re-run profiling

```powershell
python scripts\profile_raw.py
```
