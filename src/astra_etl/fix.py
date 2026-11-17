r"""Fix rows in quarantine (dataset.quarantine_record), as astra_analyst.

Run from the project folder, in PowerShell or cmd:
  .\astra fix list    [--table T] [--rule R] [--limit N]    rows in quarantine, no values
  .\astra fix show    TABLE KEY                             rule, columns, current values, edits
  .\astra fix set     TABLE KEY COLUMN VALUE --reason "..." [--id N] [--blank]
                      (--id N picks the row by id; KEY may then be -, e.g. for a blank key)
  .\astra fix drop    QUARANTINE_ID --reason "..."          remove a row that should never load
  .\astra fix history [--table T] [--key K] [--limit N]     edit log (old and new values)

`set` changes the value inside the quarantine row; the old value goes to dataset.quarantine_edit.
The next ETL run (.\astra etl) rechecks the row: if it passes it is loaded, archived as GRADUATED
and removed from quarantine. Source files are never changed or re-read.
`drop` archives the row as DROPPED (with your reason) and removes it. It never touches loaded data.
`show` and `history` print raw values, which may be personal data: use them only on your own machine.
"""
from __future__ import annotations

import argparse
import sys

from .db import connect
from .spec import SPEC_BY_NAME

MAX_VALUE = 500


def _source_columns(table: str) -> list[str]:
    return [c.source for c in SPEC_BY_NAME[table].columns]


def _pk_source(table: str) -> str:
    spec = SPEC_BY_NAME[table]
    return next(c.source for c in spec.columns if c.target == spec.pk)


def _reason(text: str) -> str:
    text = text.strip()
    if not 3 <= len(text) <= 300:
        raise SystemExit("--reason must be 3 to 300 characters")
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="astra fix")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--table", choices=sorted(SPEC_BY_NAME))
    p.add_argument("--rule")
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("show")
    p.add_argument("table", choices=sorted(SPEC_BY_NAME))
    p.add_argument("key")
    p = sub.add_parser("set")
    p.add_argument("table", choices=sorted(SPEC_BY_NAME))
    p.add_argument("key")
    p.add_argument("column")
    p.add_argument("value", nargs="?")
    p.add_argument("--reason", required=True)
    p.add_argument("--id", type=int, help="quarantine id, when several rows share the key")
    p.add_argument("--blank", action="store_true", help="make the cell blank instead of VALUE")
    p = sub.add_parser("drop")
    p.add_argument("quarantine_id", type=int)
    p.add_argument("--reason", required=True)
    p = sub.add_parser("history")
    p.add_argument("--table", choices=sorted(SPEC_BY_NAME))
    p.add_argument("--key")
    p.add_argument("--limit", type=int, default=50)
    a = ap.parse_args(argv)

    conn = connect("analyst")
    try:
        with conn.cursor() as cur:
            rc = _run(cur, a)
        if rc == 0:
            conn.commit()
        else:
            conn.rollback()
        return rc
    finally:
        conn.close()


def _run(cur, a) -> int:
    if a.cmd == "list":
        cur.execute("SELECT quarantine_id, table_name, record_key, rule_id, failed_columns, depends_on, "
                    "source_file, source_row_number FROM dataset.quarantine_record "
                    "WHERE (%(t)s::text IS NULL OR table_name = %(t)s) AND (%(r)s::text IS NULL OR rule_id = %(r)s) "
                    "ORDER BY table_name, rule_id, record_key, quarantine_id LIMIT %(n)s",
                    {"t": a.table, "r": a.rule and a.rule.upper(), "n": max(1, min(a.limit, 1000))})
        rows = cur.fetchall()
        for qid, t, k, r, cols, dep, f, line in rows:
            print(f"id={qid:<7} {t:18} {k or '-':14} {r:27} fix={','.join(cols)}"
                  + (f" waits_for={dep}" if dep else "") + f"  ({f} line {line})")
        if not rows:
            print("nothing in quarantine for that filter")
        return 0

    if a.cmd == "show":
        cur.execute("SELECT q.quarantine_id, q.rule_id, q.failed_columns, q.depends_on, q.source_file, "
                    "q.source_row_number, q.raw_record, q.corrected_columns, r.remediation "
                    "FROM dataset.quarantine_record q JOIN dataset.quarantine_rule r USING (rule_id) "
                    "WHERE q.table_name = %s AND upper(q.record_key) = upper(%s) ORDER BY q.quarantine_id",
                    (a.table, a.key))
        rows = cur.fetchall()
        if not rows:
            print("no row in quarantine for that key (it may have graduated: see .\\astra fix history)")
        for qid, rule, cols, dep, f, line, raw, edited, remedy in rows:
            print(f"id {qid}: rule {rule} ({f} line {line})\n  fix: {', '.join(cols)}\n  how: {remedy}")
            if dep:
                print(f"  waits for: {dep}")
            for k in _source_columns(a.table):
                mark = " <- fix" if k in cols else (" (edited)" if k in (edited or []) else "")
                print(f"    {k:26} = {raw.get(k)!r}{mark}")
        _print_history(cur, a.table, a.key, 20)
        return 0

    if a.cmd == "set":
        if a.column not in _source_columns(a.table):
            print(f"unknown column for {a.table}; use one of: {', '.join(_source_columns(a.table))}")
            return 2
        if a.blank == (a.value is not None):
            print("give VALUE or --blank (not both)")
            return 2
        reason = _reason(a.reason)
        value = None if a.blank else a.value
        if value is not None and len(value) > MAX_VALUE:
            print(f"value is longer than {MAX_VALUE} characters")
            return 2
        cur.execute("SELECT quarantine_id, source_file, source_row_number, record_key, raw_record ->> %(c)s "
                    "FROM dataset.quarantine_record WHERE table_name = %(t)s AND CASE WHEN %(id)s::bigint IS NULL "
                    "THEN upper(record_key) = upper(%(k)s) ELSE quarantine_id = %(id)s END FOR UPDATE",
                    {"c": a.column, "t": a.table, "k": a.key, "id": a.id})
        rows = cur.fetchall()
        if not rows:
            print("no row in quarantine for that key" + (" and id" if a.id else ""))
            return 2
        if len(rows) > 1:
            print("several rows share this key; repeat with --id N, one of: " + ", ".join(str(r[0]) for r in rows))
            return 2
        qid, src, line, key, old = rows[0]
        new_key = ((value or "").strip().upper()[:64] or None) if a.column == _pk_source(a.table) else key
        cur.execute("UPDATE dataset.quarantine_record SET raw_record = jsonb_set(raw_record, ARRAY[%s], to_jsonb(%s::text)), "
                    "corrected_columns = (SELECT array_agg(DISTINCT c ORDER BY c) FROM unnest(corrected_columns || %s::text) c), "
                    "record_key = %s WHERE quarantine_id = %s",
                    (a.column, value or "", a.column, new_key, qid))
        cur.execute("INSERT INTO dataset.quarantine_edit (quarantine_id, table_name, source_file, source_row_number, "
                    "record_key, column_name, old_value, new_value, reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "RETURNING edit_id",
                    (qid, a.table, src, line, key, a.column, old, value, reason))
        print(f"edit #{cur.fetchone()[0]} saved on quarantine id {qid}; the next ETL run rechecks it: .\\astra etl")
        return 0

    if a.cmd == "drop":
        cur.execute(
            "WITH gone AS (DELETE FROM dataset.quarantine_record WHERE quarantine_id = %(id)s "
            "  RETURNING quarantine_id, table_name, source_file, source_row_number, record_key, rule_id, issue_code, "
            "            failed_columns, depends_on, corrected_columns, run_id, created_at) "
            "INSERT INTO dataset.quarantine_archive (quarantine_id, table_name, source_file, source_row_number, "
            "  record_key, rule_id, issue_code, failed_columns, depends_on, edited_columns, first_run_id, created_at, "
            "  resolution, note) "
            "SELECT quarantine_id, table_name, source_file, source_row_number, record_key, rule_id, issue_code, "
            "       failed_columns, depends_on, corrected_columns, run_id, created_at, 'DROPPED', %(note)s FROM gone",
            {"id": a.quarantine_id, "note": _reason(a.reason)})
        print("dropped and archived" if cur.rowcount else "no row in quarantine with that id")
        return 0 if cur.rowcount else 2

    if a.cmd == "history":
        _print_history(cur, a.table, a.key, max(1, min(a.limit, 1000)))
        return 0
    return 2


def _print_history(cur, table: str | None, key: str | None, limit: int) -> None:
    cur.execute("SELECT e.edit_id, e.edited_at, e.table_name, e.record_key, e.column_name, e.old_value, e.new_value, "
                "e.reason, e.edited_by, e.quarantine_id, "
                "(SELECT a.resolution FROM dataset.quarantine_archive a WHERE a.quarantine_id = e.quarantine_id "
                " ORDER BY a.archive_id DESC LIMIT 1) "
                "FROM dataset.quarantine_edit e "
                "WHERE (%(t)s::text IS NULL OR e.table_name = %(t)s) AND (%(k)s::text IS NULL OR upper(e.record_key) = upper(%(k)s)) "
                "ORDER BY e.edit_id DESC LIMIT %(n)s", {"t": table, "k": key, "n": limit})
    rows = cur.fetchall()
    if rows:
        print("edits (newest first):")
    for eid, at, t, k, col, old, new, reason, who, qid, resolution in rows:
        state = resolution or ("in quarantine" if qid else "legacy correction")
        print(f"  #{eid} {at:%Y-%m-%d %H:%M} {t} {k} {col}: {old!r} -> {new!r}  by {who}: {reason}  [{state}]")


if __name__ == "__main__":
    sys.exit(main())
