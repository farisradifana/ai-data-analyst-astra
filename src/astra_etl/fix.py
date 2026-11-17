"""Fix quarantined rows in the database (dataset.quarantine_correction), as astra_analyst.

  python -m astra_etl.fix list   [--table T] [--rule R] [--limit N]   open quarantine, no values
  python -m astra_etl.fix show   TABLE KEY                            rule, columns, current raw values
  python -m astra_etl.fix set    TABLE KEY COLUMN VALUE --reason "..." [--line N] [--blank]
  python -m astra_etl.fix off    CORRECTION_ID                        withdraw (is_active = false)
  python -m astra_etl.fix status                                      corrections and last outcome

A correction takes effect on the next ETL run (python -m astra_etl). The source CSV is not changed.
`show` prints raw values, which may be personal data: use it only on your own machine.
"""
from __future__ import annotations

import argparse
import sys

from .db import connect
from .spec import SPEC_BY_NAME
from .transform import Correction


def fetch_corrections(conn) -> list[Correction]:
    with conn.cursor() as cur:
        cur.execute("SELECT correction_id, table_name, record_key, source_row_number, column_name, corrected_value "
                    "FROM dataset.quarantine_correction WHERE is_active ORDER BY correction_id")
        return [Correction(*row) for row in cur.fetchall()]


def _source_columns(table: str) -> list[str]:
    return [c.source for c in SPEC_BY_NAME[table].columns]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="astra_etl.fix")
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
    p.add_argument("--line", type=int, help="only this source line (for a shared key)")
    p.add_argument("--blank", action="store_true", help="make the cell blank instead of VALUE")
    p = sub.add_parser("off")
    p.add_argument("correction_id", type=int)
    sub.add_parser("status")
    a = ap.parse_args(argv)

    conn = connect("analyst")
    try:
        with conn.cursor() as cur:
            if a.cmd == "list":
                cur.execute("SELECT table_name, record_key, rule_id, failed_columns, depends_on, source_row_number "
                            "FROM dataset.quarantine_record WHERE status = 'OPEN' "
                            "AND (%(t)s::text IS NULL OR table_name = %(t)s) AND (%(r)s::text IS NULL OR rule_id = %(r)s) "
                            "ORDER BY table_name, rule_id, record_key LIMIT %(n)s",
                            {"t": a.table, "r": a.rule and a.rule.upper(), "n": max(1, min(a.limit, 1000))})
                for t, k, r, cols, dep, line in cur.fetchall():
                    print(f"{t:18} {k or '-':14} line={line:<7} {r:27} fix={','.join(cols)}"
                          + (f" waits_for={dep}" if dep else ""))
            elif a.cmd == "show":
                cur.execute("SELECT q.rule_id, q.failed_columns, q.depends_on, q.source_row_number, q.raw_record, "
                            "r.remediation FROM dataset.quarantine_record q JOIN dataset.quarantine_rule r USING (rule_id) "
                            "WHERE q.status = 'OPEN' AND q.table_name = %s AND upper(q.record_key) = upper(%s) "
                            "ORDER BY q.source_row_number", (a.table, a.key))
                rows = cur.fetchall()
                if not rows:
                    print("no OPEN quarantine record for that key")
                for rule, cols, dep, line, raw, remedy in rows:
                    print(f"rule {rule} (line {line})\n  fix: {', '.join(cols)}\n  how: {remedy}")
                    if dep:
                        print(f"  waits for: {dep}")
                    for k in _source_columns(a.table):
                        mark = " <-" if k in cols else ""
                        print(f"    {k:26} = {raw.get(k)!r}{mark}")
                cur.execute("SELECT correction_id, column_name, corrected_value, source_row_number, last_outcome "
                            "FROM dataset.quarantine_correction WHERE is_active AND table_name = %s "
                            "AND upper(record_key) = upper(%s) ORDER BY correction_id", (a.table, a.key))
                for cid, col, val, line, outcome in cur.fetchall():
                    print(f"  correction #{cid}: {col} = {val!r}" + (f" (line {line})" if line else "")
                          + f" last_outcome={outcome or 'NOT_YET_APPLIED'}")
            elif a.cmd == "set":
                if a.column not in _source_columns(a.table):
                    print(f"unknown column for {a.table}; use one of: {', '.join(_source_columns(a.table))}")
                    return 2
                if a.blank == (a.value is not None):
                    print("give VALUE or --blank (not both)")
                    return 2
                cur.execute("UPDATE dataset.quarantine_correction SET is_active = false, updated_at = now() "
                            "WHERE is_active AND table_name = %s AND upper(record_key) = upper(%s) "
                            "AND coalesce(source_row_number, 0) = coalesce(%s, 0) AND column_name = %s",
                            (a.table, a.key, a.line, a.column))
                replaced = cur.rowcount
                cur.execute("INSERT INTO dataset.quarantine_correction (table_name, record_key, source_row_number, "
                            "column_name, corrected_value, reason) VALUES (%s, %s, %s, %s, %s, %s) "
                            "RETURNING correction_id",
                            (a.table, a.key, a.line, a.column, None if a.blank else a.value, a.reason))
                cid = cur.fetchone()[0]
                print(f"correction #{cid} saved" + (" (replaced the previous one)" if replaced else "")
                      + "; it applies on the next ETL run: python -m astra_etl")
            elif a.cmd == "off":
                cur.execute("UPDATE dataset.quarantine_correction SET is_active = false, updated_at = now() "
                            "WHERE correction_id = %s AND is_active", (a.correction_id,))
                print("withdrawn" if cur.rowcount else "no active correction with that id")
            elif a.cmd == "status":
                cur.execute("SELECT table_name, column_name, is_active, last_outcome, corrections "
                            "FROM dataset.v_correction_status ORDER BY 1, 2, 3 DESC, 4")
                rows = cur.fetchall()
                for t, col, active, outcome, n in rows:
                    print(f"{t:18} {col:24} {'active' if active else 'withdrawn':9} {outcome:18} {n}")
                if not rows:
                    print("no corrections yet")
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
