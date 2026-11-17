"""Astra ETL (SYNTHETIC data): raw CSV -> validated rows -> Supabase schema `dataset`.

Deterministic rules decide pass/fail. Rows that fail go to dataset.quarantine_record.
Run (PowerShell or cmd): .\\astra etl --dry-run   (no database writes)
                         .\\astra etl             (load)
"""
