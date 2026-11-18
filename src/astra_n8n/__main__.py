"""CLI: python -m astra_n8n build | lint | check-live   (via .\\astra n8n ...)."""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from astra_n8n.assistant import TOOLS, Tool, build_workflow, placeholders, to_psycopg, write_workflow

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "n8n" / "build" / "astra_data_assistant.json"
TELEGRAM_OUT_NAME = "astra_telegram_assistant.json"   # written next to DEFAULT_OUT
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|grant|revoke|truncate|copy|call|do|execute|set|reset|"
    r"vacuum|analyze|lock|listen|notify|pg_sleep|pg_read_file|lo_import|dblink)\b", re.I)


def lint_tool(t: Tool) -> list[str]:
    """Static checks: one read-only SELECT on dataset.v_* views, values only through $n parameters."""
    problems = []
    sql = t.sql.strip()
    if not re.match(r"(?is)^(select|with)\b", sql):
        problems.append("does not start with SELECT")
    if ";" in sql:
        problems.append("contains ';'")
    if "{{" in sql or "$fromAI" in sql or "$json" in sql:
        problems.append("n8n expression inside the SQL text")
    if "%" in sql:
        problems.append("contains '%'")
    if "--" in sql or "/*" in sql:
        problems.append("contains a comment")
    bad = sorted({m.group(0).lower() for m in FORBIDDEN.finditer(sql)})
    if bad:
        problems.append(f"forbidden keyword {bad}")
    for rel in re.findall(r"(?i)\b(?:from|join)\s+([a-z_][\w.]*)", sql):
        if not re.fullmatch(r"dataset\.v_[a-z_]+", rel):
            problems.append(f"reads {rel}, not a dataset.v_* view")
    if placeholders(sql) != list(range(1, len(t.params) + 1)):
        problems.append(f"placeholders {placeholders(sql)} do not match {len(t.params)} parameter(s)")
    if not re.fullmatch(r"get_[a-z_]+", t.name):
        problems.append("tool name must be get_*")
    return problems


def cmd_lint() -> int:
    bad = 0
    for t in TOOLS:
        p = lint_tool(t)
        bad += bool(p)
        print(f"{t.name:28} {'OK' if not p else 'FAIL: ' + '; '.join(p)}")
    return 1 if bad else 0


def cmd_build(out: Path) -> int:
    if any(lint_tool(t) for t in TOOLS):
        print("lint failed; run: .\\astra n8n lint")
        return 1
    from astra_etl.db import load_env

    try:
        model = load_env().get("LLM_MODEL", "")
    except RuntimeError:
        model = ""
    try:
        path = write_workflow(out, model)
        tg_path = write_workflow(out.with_name(TELEGRAM_OUT_NAME), model, "webhook")
    except ValueError as e:
        print(f"error: {e}")
        return 2
    wf = build_workflow(model)
    print(f"wrote {path} ({len(wf['nodes'])} nodes, {len(TOOLS)} tools)")
    print(f"wrote {tg_path} (webhook for the Telegram bridge, doc 36)")
    if not model:
        print("LLM_MODEL is empty in .env: the model node says SET_LLM_MODEL. Set it, then build again.")
    return 0


# 2025 reference values (doc 34). check-live compares the tools against them.
REFERENCE_2025 = {
    ("get_sales_kpis", "net_revenue"): 54269362661171,
    ("get_sales_kpis", "completed_transactions"): 44689,
    ("get_sales_kpis", "gross_margin_pct"): 18.53,
    ("get_service_kpis", "service_revenue"): 69266735528,
    ("get_service_kpis", "completed_orders"): 3618,
    ("get_procurement_inventory", "po_count"): 6845,
    ("get_attendance_kpis", "attendance_rate_pct"): 82.04,
    ("get_attendance_kpis", "average_hours_worked"): 8.98,
}
SAMPLE = {"from_date": "2025-01-01", "to_date": "2025-12-31", "branch": "ALL", "dimension": "BRANCH"}


def cmd_check_live() -> int:
    """Run every tool as astra_reporting in a READ ONLY transaction; compare with the 2025 references."""
    from astra_etl.db import connect

    conn = connect("reporting")
    ok = True
    try:
        cur = conn.cursor()
        cur.execute("BEGIN READ ONLY")
        cur.execute("SET LOCAL statement_timeout = '20s'")
        for t in TOOLS:
            args = {f"p{i}": SAMPLE[p.name] for i, p in enumerate(t.params, start=1)}
            t0 = time.perf_counter()
            cur.execute(to_psycopg(t.sql), args)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            line = f"{t.name:28} rows={len(rows):>3} {time.perf_counter() - t0:5.2f}s"
            for (tool, col), want in REFERENCE_2025.items():
                if tool != t.name:
                    continue
                got = rows[0][cols.index(col)] if rows else None
                match = got is not None and abs(float(got) - want) <= (0.005 if isinstance(want, float) else 1)
                ok &= match
                line += f"  {col}={'MATCH' if match else f'MISMATCH ({got} != {want})'}"
            print(line)
        # The role must not be able to write, even inside this tool path.
        cur.execute("SELECT has_table_privilege(current_user, 'dataset.sales_transactions', 'INSERT')")
        can_write = cur.fetchone()[0]
        print(f"reporting role can INSERT: {can_write}")
        ok &= not can_write
    finally:
        conn.rollback()
        conn.close()
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=".\\astra n8n", description="Astra data assistant for n8n (doc 35)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the n8n workflow JSON (model from LLM_MODEL in .env)")
    b.add_argument("--out", type=Path, default=DEFAULT_OUT)
    sub.add_parser("lint", help="static checks of every tool query")
    sub.add_parser("check-live", help="run every tool as astra_reporting (read only) and compare with 2025")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        return cmd_build(a.out)
    if a.cmd == "lint":
        return cmd_lint()
    return cmd_check_live()


if __name__ == "__main__":
    sys.exit(main())
