"""Load validated rows into schema `dataset` in one transaction (as astra_analyst).

- etl_run row is committed first (status RUNNING) so a crash stays visible.
- Business rows: INSERT ... ON CONFLICT (pk) DO UPDATE (idempotent re-runs, no DELETE).
- Quarantine lifecycle per table: OPEN records of earlier runs become
    SUPERSEDED  key is quarantined again by this run (the new OPEN record replaces it)
    GRADUATED   key now loaded into the valid table
    DISMISSED   key no longer in the source file
  then this run's quarantine rows are inserted as OPEN, and exact duplicates as DISMISSED
  (rule EXACT_DUPLICATE_ROW). Every record carries rule_id, failed_columns and depends_on.
- Corrections: each active dataset.quarantine_correction gets last_outcome for this run
  (LOADED | STILL_QUARANTINED | KEY_NOT_FOUND | COLUMN_UNKNOWN).
- commit=False runs everything in one transaction and leaves it open (caller inspects, then
  rolls back): used for end-to-end checks without changing data.
- etl_run_file (checksum + reconciliation) and dq_check_result (counts per rule_id).
- Any error -> ROLLBACK of the data transaction, etl_run marked FAILED (error class only).
Known limit: a row loaded by an earlier run and quarantined now stays in its table (no DELETE
privilege by design); it is flagged by etl_run_id being older than the latest run.
"""
from __future__ import annotations

import time

from psycopg2.extras import Json, execute_values

from .rules import RULES
from .spec import SPECS
from .transform import TableResult

PAGE = 2000


def _upsert(cur, res: TableResult, run_id: str) -> None:
    spec = res.spec
    cols = [c.target for c in spec.columns] + ["etl_run_id", "source_row_number"]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != spec.pk) + ", loaded_at = now()"
    sql = (f"INSERT INTO dataset.{spec.name} ({', '.join(cols)}) VALUES %s "
           f"ON CONFLICT ({spec.pk}) DO UPDATE SET {updates}")
    data = [tuple(row[c.target] for c in spec.columns) + (run_id, line) for line, row in res.rows]
    execute_values(cur, sql, data, page_size=PAGE)


def _close_previous(cur, res: TableResult, run_id: str) -> None:
    name = res.spec.name
    cur.execute("SELECT EXISTS (SELECT 1 FROM dataset.quarantine_record WHERE table_name = %s "
                "AND status = 'OPEN' AND run_id <> %s)", (name, run_id))
    if not cur.fetchone()[0]:
        return
    held = sorted({q.record_key for q in res.quarantined if q.record_key})
    loaded = sorted(res.loaded_keys())
    cur.execute(
        "UPDATE dataset.quarantine_record SET resolved_at = now(), resolved_run_id = %(run)s, status = "
        "CASE WHEN record_key = ANY(%(held)s) THEN 'SUPERSEDED' "
        "     WHEN record_key = ANY(%(loaded)s) THEN 'GRADUATED' ELSE 'DISMISSED' END "
        "WHERE table_name = %(t)s AND status = 'OPEN' AND run_id <> %(run)s",
        {"run": run_id, "held": held, "loaded": loaded, "t": name})


def _quarantine(cur, res: TableResult, run_id: str) -> None:
    _close_previous(cur, res, run_id)
    data = [(run_id, res.spec.name, q.line, q.record_key, q.issue_code, q.rule_id, q.failed_columns,
             q.depends_on, q.corrected_columns, q.issue_detail, Json(q.raw), "OPEN", None, None)
            for q in res.quarantined]
    data += [(run_id, res.spec.name, q.line, q.record_key, q.issue_code, q.rule_id, q.failed_columns,
              q.depends_on, q.corrected_columns, q.issue_detail, Json(q.raw), "DISMISSED", "now", run_id)
             for q in res.duplicates]
    if data:
        execute_values(cur, "INSERT INTO dataset.quarantine_record (run_id, table_name, source_row_number, "
                            "record_key, issue_code, rule_id, failed_columns, depends_on, corrected_columns, "
                            "issue_detail, raw_record, status, resolved_at, resolved_run_id) VALUES %s",
                       data, template="(%s,%s,%s,%s,%s,%s,%s::text[],%s,%s::text[],%s,%s,%s,%s::timestamptz,%s::uuid)",
                       page_size=PAGE)
    if res.correction_outcome:
        execute_values(cur, "UPDATE dataset.quarantine_correction c SET last_outcome = v.outcome, "
                            "last_applied_run_id = v.run_id, last_applied_at = now() "
                            "FROM (VALUES %s) AS v(id, outcome, run_id) WHERE c.correction_id = v.id",
                       [(cid, outcome, run_id) for cid, outcome in sorted(res.correction_outcome.items())],
                       template="(%s::bigint, %s::text, %s::uuid)")


def _audit(cur, res: TableResult, run_id: str) -> None:
    cur.execute("INSERT INTO dataset.etl_run_file (run_id, table_name, file_name, file_sha256, rows_read, "
                "rows_loaded, rows_quarantined, rows_duplicate) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (run_id, res.spec.name, res.spec.file, res.file_sha256, res.rows_read,
                 res.rows_loaded, len(res.quarantined), res.rows_duplicate))
    counts = res.rule_counts()
    checks = [(r.lower(), counts.get(r, 0), "INFO" if RULES[r].graduation_path == "NOT_NEEDED" else "ERROR")
              for r in sorted(set(counts) | {"EXACT_DUPLICATE_ROW"})]
    execute_values(cur, "INSERT INTO dataset.dq_check_result (run_id, table_name, check_name, failed_rows, "
                        "checked_rows, severity) VALUES %s",
                   [(run_id, res.spec.name, name, n, res.rows_read, sev) for name, n, sev in checks])


def load(conn, results: dict[str, TableResult], trigger: str, code_version: str | None, log=print,
         commit: bool = True) -> str:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO dataset.etl_run (trigger_type, code_version) VALUES (%s, %s) RETURNING run_id",
                    (trigger, code_version))
        run_id = cur.fetchone()[0]
    if commit:
        conn.commit()
    log(f"run {run_id} started")
    try:
        with conn.cursor() as cur:
            for spec in SPECS:
                res = results[spec.name]
                t0 = time.perf_counter()
                _upsert(cur, res, run_id)
                _quarantine(cur, res, run_id)
                _audit(cur, res, run_id)
                log(f"  {spec.name:20} loaded={res.rows_loaded:>7} quarantined={len(res.quarantined):>5} "
                    f"duplicate={res.rows_duplicate:>4} {time.perf_counter() - t0:5.1f}s")
            cur.execute("UPDATE dataset.etl_run SET status = 'SUCCEEDED', finished_at = now() WHERE run_id = %s",
                        (run_id,))
        if commit:
            conn.commit()
    except Exception as exc:
        conn.rollback()
        if not commit:
            raise
        with conn.cursor() as cur:
            cur.execute("UPDATE dataset.etl_run SET status = 'FAILED', finished_at = now(), notes = %s "
                        "WHERE run_id = %s", (f"error: {type(exc).__name__}", run_id))
        conn.commit()
        raise
    return run_id
