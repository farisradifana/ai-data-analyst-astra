"""Astra ETL (SYNTHETIC data): raw CSV -> validated rows -> Supabase schema `dataset`.

Deterministic rules decide pass/fail. Rows that fail go to dataset.quarantine_record.
Run: PYTHONPATH=src python -m astra_etl --dry-run   (no database writes)
     PYTHONPATH=src python -m astra_etl             (load)
"""
