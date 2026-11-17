"""CLI: PYTHONPATH=src python -m astra_etl [--dry-run] [--trigger MANUAL|SCHEDULED|REPROCESS]

Writes a counts-only summary to reports/etl/last_run_summary.json and .md (no record content).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time

from .db import ROOT, connect
from .spec import SPECS
from .transform import transform


def _git_version() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


def write_summary(results, mode: str, run_id: str | None) -> None:
    out = ROOT / "reports" / "etl"
    out.mkdir(parents=True, exist_ok=True)
    tables = []
    for spec in SPECS:
        r = results[spec.name]
        tables.append({"table": spec.name, "file_sha256": r.file_sha256, "rows_read": r.rows_read,
                       "rows_loaded": r.rows_loaded, "rows_quarantined": len(r.quarantined),
                       "rows_duplicate": r.rows_duplicate, "rules": dict(sorted(r.rule_counts().items()))})
    summary = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "mode": mode, "run_id": run_id, "tables": tables,
               "totals": {k: sum(t[k] for t in tables) for k in
                          ("rows_read", "rows_loaded", "rows_quarantined", "rows_duplicate")}}
    (out / "last_run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [f"# ETL run summary ({mode})", "", f"Generated: {summary['generated_at']}  ",
             f"Run id: {run_id or 'n/a (dry run)'}", "",
             "| Table | Read | Loaded | Quarantined | Duplicate | Rules (quarantine + duplicate) |", "|---|---:|---:|---:|---:|---|"]
    for t in tables:
        issues = ", ".join(f"{k} {v}" for k, v in t["rules"].items()) or "-"
        lines.append(f"| {t['table']} | {t['rows_read']:,} | {t['rows_loaded']:,} | {t['rows_quarantined']:,} "
                     f"| {t['rows_duplicate']:,} | {issues} |")
    tot = summary["totals"]
    lines.append(f"| **TOTAL** | **{tot['rows_read']:,}** | **{tot['rows_loaded']:,}** | "
                 f"**{tot['rows_quarantined']:,}** | **{tot['rows_duplicate']:,}** | |")
    (out / "last_run_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="astra_etl")
    ap.add_argument("--dry-run", action="store_true", help="validate only, no database writes")
    ap.add_argument("--trigger", default="MANUAL", choices=["MANUAL", "SCHEDULED", "REPROCESS"])
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    results = transform(ROOT / "raw-data")
    print(f"transform ok in {time.perf_counter() - t0:.1f}s")
    run_id = None
    if not args.dry_run:
        from .load import load  # needs psycopg2; dry runs do not

        conn = connect("analyst")
        try:
            run_id = str(load(conn, results, args.trigger, _git_version()))
        finally:
            conn.close()
    write_summary(results, "dry-run" if args.dry_run else "load", run_id)
    for spec in SPECS:
        r = results[spec.name]
        print(f"  {spec.name:20} read={r.rows_read:>7} loaded={r.rows_loaded:>7} "
              f"quarantined={len(r.quarantined):>5} duplicate={r.rows_duplicate:>4}")
    print(f"done in {time.perf_counter() - t0:.1f}s; summary: reports/etl/last_run_summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
