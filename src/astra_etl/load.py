"""Database side of the ETL (as astra_analyst): read state, then write one run in one transaction.

read_state():   registered files, rows in quarantine, primary keys already loaded.
new_files():    files under raw-data not registered yet. A registered name whose checksum changed is
                an error: an ingested file is never read again, so new data must come as a new file.
load():
- etl_run row is committed first (status RUNNING) so a crash stays visible.
- Per table, parents first:
    INSERT the rows that passed (plain INSERT: a key that is already loaded never gets here, it is
      quarantined as DUPLICATE_PRIMARY_KEY or dropped as EXACT_DUPLICATE_ROW).
    Quarantine rows that passed -> copied to quarantine_archive (GRADUATED) and deleted.
    Quarantine rows that became exact duplicates -> archived (DUPLICATE_DROPPED) and deleted.
    Quarantine rows that still fail -> labels refreshed (rule, columns, depends_on, last check).
    New failing rows -> INSERTed into quarantine; new exact duplicates -> archived directly.
    New files -> dataset.source_file; etl_run_file per file; dq_check_result per rule.
- commit=False leaves the transaction open (caller inspects, then rolls back).
- Any error -> ROLLBACK, etl_run marked FAILED (error class only).
A session advisory lock (lock()) keeps two runs from working on the same state.
"""
from __future__ import annotations

import pathlib
import time

from psycopg2.extras import Json, execute_values

from .rules import RULES
from .spec import SPECS
from .transform import OpenRecord, SourceFile, TableResult, discover, read_source, sha256_file

PAGE = 2000
LOCK_KEY = 730_420_118  # pg advisory lock: one ETL run at a time


def lock(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
        ok = cur.fetchone()[0]
    conn.commit()
    if not ok:
        raise RuntimeError("another ETL run is in progress; try again when it has finished")


def read_state(conn) -> tuple[dict, dict[str, list[OpenRecord]], dict[str, set[str]]]:
    """(registered {(table, name): sha}, open records per table, loaded keys per table)."""
    with conn.cursor() as cur:
        cur.execute("SELECT table_name, file_name, file_sha256 FROM dataset.source_file")
        registered = {(t, n): s for t, n, s in cur.fetchall()}
        cur.execute("SELECT quarantine_id, table_name, source_file, source_row_number, raw_record, corrected_columns "
                    "FROM dataset.quarantine_record ORDER BY table_name, source_file, source_row_number")
        open_records: dict[str, list[OpenRecord]] = {}
        for qid, t, f, line, raw, edited in cur.fetchall():
            open_records.setdefault(t, []).append(OpenRecord(qid, f, line, raw, list(edited or [])))
        keys = {}
        for spec in SPECS:
            cur.execute(f"SELECT {spec.pk} FROM dataset.{spec.name}")
            keys[spec.name] = {k for (k,) in cur.fetchall()}
    conn.rollback()
    return registered, open_records, keys


def existing_rows(conn):
    def fetch(table: str, keys: list[str]) -> dict[str, tuple]:
        spec = next(s for s in SPECS if s.name == table)
        cols = [c.target for c in spec.columns]
        with conn.cursor() as cur:
            cur.execute(f"SELECT {', '.join(cols)} FROM dataset.{table} WHERE {spec.pk} = ANY(%s)", (keys,))
            return {row[cols.index(spec.pk)]: tuple(row) for row in cur.fetchall()}
    return fetch


def new_files(raw_dir: pathlib.Path, registered: dict, log=print) -> dict[str, list[SourceFile]]:
    out: dict[str, list[SourceFile]] = {}
    known_sha = {(t, s) for (t, _), s in registered.items()}
    for table, found in discover(raw_dir).items():
        for name, path in found:
            if (table, name) in registered:
                if sha256_file(path) != registered[(table, name)]:
                    raise RuntimeError(f"{name} changed after it was loaded. Ingested files are never re-read: "
                                       f"restore it, and put new data in a new file under raw-data/{table}/")
                continue
            src = read_source(table, name, path)
            if (table, src.sha256) in known_sha:
                log(f"  skip {name}: same content as a file already loaded")
                continue
            known_sha.add((table, src.sha256))
            out.setdefault(table, []).append(src)
    return out


# --- writes ----------------------------------------------------------------------------------

def _insert_rows(cur, res: TableResult, run_id: str) -> None:
    if not res.rows:
        return
    spec = res.spec
    cols = [c.target for c in spec.columns] + ["etl_run_id", "source_row_number"]
    data = [tuple(r.row[c.target] for c in spec.columns) + (run_id, r.line) for r in res.rows]
    execute_values(cur, f"INSERT INTO dataset.{spec.name} ({', '.join(cols)}) VALUES %s", data, page_size=PAGE)


def _leave_quarantine(cur, ids: list[int], resolution: str, run_id: str) -> None:
    """Copy to the archive (labels only, no raw values) and delete, in one statement."""
    if not ids:
        return
    cur.execute(
        "WITH gone AS (DELETE FROM dataset.quarantine_record WHERE quarantine_id = ANY(%(ids)s) "
        "  RETURNING quarantine_id, table_name, source_file, source_row_number, record_key, rule_id, issue_code, "
        "            failed_columns, depends_on, corrected_columns, run_id, created_at) "
        "INSERT INTO dataset.quarantine_archive (quarantine_id, table_name, source_file, source_row_number, "
        "  record_key, rule_id, issue_code, failed_columns, depends_on, edited_columns, first_run_id, created_at, "
        "  resolution, resolved_run_id) "
        "SELECT quarantine_id, table_name, source_file, source_row_number, record_key, rule_id, issue_code, "
        "       failed_columns, depends_on, corrected_columns, run_id, created_at, %(res)s, %(run)s FROM gone",
        {"ids": ids, "res": resolution, "run": run_id})
    if cur.rowcount != len(ids):
        raise RuntimeError(f"quarantine changed during the run ({cur.rowcount} of {len(ids)} rows archived)")


def _quarantine(cur, res: TableResult, run_id: str) -> None:
    name = res.spec.name
    _leave_quarantine(cur, res.graduated, "GRADUATED", run_id)
    _leave_quarantine(cur, [q.quarantine_id for q in res.duplicates if q.quarantine_id is not None],
                      "DUPLICATE_DROPPED", run_id)
    if res.still_open:
        execute_values(
            cur, "UPDATE dataset.quarantine_record q SET record_key = v.key, rule_id = v.rule, issue_code = v.code, "
                 "failed_columns = v.cols, depends_on = v.dep, issue_detail = v.detail, "
                 "last_checked_run_id = v.run, last_checked_at = now() "
                 "FROM (VALUES %s) AS v(id, key, rule, code, cols, dep, detail, run) WHERE q.quarantine_id = v.id",
            [(q.quarantine_id, q.record_key, q.rule_id, q.issue_code, q.failed_columns, q.depends_on,
              q.issue_detail, run_id) for q in res.still_open],
            template="(%s::bigint, %s::text, %s::text, %s::text, %s::text[], %s::text, %s::text, %s::uuid)",
            page_size=PAGE)
    if res.new_quarantine:
        execute_values(
            cur, "INSERT INTO dataset.quarantine_record (run_id, table_name, source_file, source_row_number, "
                 "record_key, issue_code, rule_id, failed_columns, depends_on, issue_detail, raw_record, status, "
                 "last_checked_run_id, last_checked_at) VALUES %s",
            [(run_id, name, q.source_file, q.line, q.record_key, q.issue_code, q.rule_id, q.failed_columns,
              q.depends_on, q.issue_detail, Json(q.raw), "OPEN", run_id) for q in res.new_quarantine],
            template="(%s,%s,%s,%s,%s,%s,%s,%s::text[],%s,%s,%s,%s,%s,now())", page_size=PAGE)
    new_dups = [q for q in res.duplicates if q.quarantine_id is None]
    if new_dups:
        execute_values(
            cur, "INSERT INTO dataset.quarantine_archive (table_name, source_file, source_row_number, record_key, "
                 "rule_id, issue_code, failed_columns, depends_on, first_run_id, created_at, resolution, "
                 "resolved_run_id) VALUES %s",
            [(name, q.source_file, q.line, q.record_key, q.rule_id, q.issue_code, q.failed_columns, q.depends_on,
              run_id, "DUPLICATE_DROPPED", run_id) for q in new_dups],
            template="(%s,%s,%s,%s,%s,%s,%s::text[],%s,%s,now(),%s,%s)", page_size=PAGE)


def _audit(cur, res: TableResult, run_id: str) -> None:
    name = res.spec.name
    for f in res.files:
        cur.execute("INSERT INTO dataset.source_file (table_name, file_name, file_sha256, rows_read, run_id) "
                    "VALUES (%s,%s,%s,%s,%s)", (name, f.name, f.sha256, f.rows_read, run_id))
        cur.execute("INSERT INTO dataset.etl_run_file (run_id, table_name, file_name, file_sha256, rows_read, "
                    "rows_loaded, rows_quarantined, rows_duplicate) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (run_id, name, f.name, f.sha256, f.rows_read, f.rows_loaded, f.rows_quarantined,
                     f.rows_duplicate))
    checks = []
    read = sum(f.rows_read for f in res.files)
    if res.files:
        counts = res.rule_counts(new_only=True)
        checks += [(r.lower(), counts.get(r, 0), read,
                    "INFO" if RULES[r].graduation_path == "NOT_NEEDED" else "ERROR")
                   for r in sorted(set(counts) | {"EXACT_DUPLICATE_ROW"})]
    if res.rechecked:
        checks.append(("quarantine_recheck", len(res.still_open), res.rechecked, "INFO"))
    if checks:
        execute_values(cur, "INSERT INTO dataset.dq_check_result (run_id, table_name, check_name, failed_rows, "
                            "checked_rows, severity) VALUES %s",
                       [(run_id, name, c, n, total, sev) for c, n, total, sev in checks])


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
                _insert_rows(cur, res, run_id)
                _quarantine(cur, res, run_id)
                _audit(cur, res, run_id)
                log(f"  {spec.name:20} files={len(res.files)} loaded={len(res.rows):>7} "
                    f"graduated={len(res.graduated):>5} in_quarantine={len(res.quarantined):>5} "
                    f"duplicate={len(res.duplicates):>4} {time.perf_counter() - t0:5.1f}s")
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
