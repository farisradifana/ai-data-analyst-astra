# ai-data-analyst-astra

SYNTHETIC enterprise data analytics simulation (Astra International Sunter Operations style).
Not affiliated with Astra International; no internal data or systems are used.

Stack: Python/pandas ETL → PostgreSQL (`astra_analytics`, schema `dataset`) → Google Looker Studio,
plus n8n + Gemini AI agent and Telegram alerts.

- Progress: [docs/STATUS.md](docs/STATUS.md)
- Steps that need a human: [docs/HUMAN-STEPS.md](docs/HUMAN-STEPS.md)
- Profiling report: [reports/profiling/profiling_summary.md](reports/profiling/profiling_summary.md)

Raw data (`raw-data/`) is intentionally not stored in Git.

## Re-run profiling

```bash
python scripts/profile_raw.py
```
