r"""ETL entry point. From the project folder, in PowerShell or cmd:

  .\astra etl [--dry-run] [--offline] [--trigger MANUAL|SCHEDULED|REPROCESS] [--no-notify]
  .\astra fix ...        (see astra_etl/fix.py)
  .\astra notify ...     (see astra_etl/notify.py)

Each run:
  1. reads only source files not loaded before: raw-data/<table>.csv and raw-data/<table>/*.csv
     (put each day's file in raw-data/<table>/, e.g. raw-data/sales_transactions/2026-11-19.csv);
  2. rechecks every row in quarantine (with the edits made by .\astra fix set);
  3. loads what passes, removes graduated rows from quarantine (archived), quarantines the rest.
--dry-run reads the database but writes nothing. --offline (dry runs only) skips the database and
treats every file as new.

Writes a counts-only summary to reports/etl/last_run_summary.json and .md (no record content).
After a load (never a dry run) it sends Telegram alerts built from that summary, when Telegram is
set up in .env (see astra_etl/notify.py). A failed load sends only the stage and the error type.
--no-notify skips the alerts. An alert that cannot be sent never fails the run.
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
from .transform import discover, read_source, transform


def _git_version() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


def _table_summary(r) -> dict:
    return {"table": r.spec.name, "new_files": [f.name for f in r.files],
            "rows_read": sum(f.rows_read for f in r.files),
            "rows_loaded_new": sum(f.rows_loaded for f in r.files),
            "rows_quarantined_new": sum(f.rows_quarantined for f in r.files),
            "rows_duplicate_new": sum(f.rows_duplicate for f in r.files),
            "quarantine_rechecked": r.rechecked, "quarantine_graduated": len(r.graduated),
            "quarantine_open_after": len(r.quarantined),
            "rules_open_after": dict(sorted(r.rule_counts(new_only=False).items()))}


def write_summary(results, mode: str, run_id: str | None) -> dict:
    out = ROOT / "reports" / "etl"
    out.mkdir(parents=True, exist_ok=True)
    tables = [_table_summary(results[spec.name]) for spec in SPECS]
    keys = ("rows_read", "rows_loaded_new", "rows_quarantined_new", "rows_duplicate_new",
            "quarantine_rechecked", "quarantine_graduated", "quarantine_open_after")
    summary = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "mode": mode, "run_id": run_id, "tables": tables,
               "totals": {k: sum(t[k] for t in tables) for k in keys}}
    (out / "last_run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [f"# ETL run summary ({mode})", "", f"Generated: {summary['generated_at']}  ",
             f"Run id: {run_id or 'n/a (dry run)'}", "",
             "New files are read once. Quarantine rows are rechecked on every run.", "",
             "| Table | New files | Read | Loaded | Quarantined | Duplicate | Rechecked | Graduated | In quarantine after |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for t in tables:
        lines.append(f"| {t['table']} | {len(t['new_files'])} | {t['rows_read']:,} | {t['rows_loaded_new']:,} "
                     f"| {t['rows_quarantined_new']:,} | {t['rows_duplicate_new']:,} | {t['quarantine_rechecked']:,} "
                     f"| {t['quarantine_graduated']:,} | {t['quarantine_open_after']:,} |")
    tot = summary["totals"]
    lines.append("| **TOTAL** | | " + " | ".join(f"**{tot[k]:,}**" for k in keys) + " |")
    lines += ["", "Rules of the rows in quarantine after the run:", ""]
    for t in tables:
        if t["rules_open_after"]:
            lines.append(f"- {t['table']}: " + ", ".join(f"{k} {v}" for k, v in t["rules_open_after"].items()))
    (out / "last_run_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


class _Stage:
    """Where the run is, for the failure alert."""
    name = "start"


def _run(args, t0: float, stage: _Stage):
    raw_dir = ROOT / "raw-data"
    stage.name = "connect"
    conn = None if args.offline else connect("analyst")
    try:
        if conn is None:
            stage.name = "read files"
            files = {t: [read_source(t, n, p) for n, p in found] for t, found in discover(raw_dir).items()}
            stage.name = "validate"
            results = transform(files)
        else:
            from .load import existing_rows, lock, new_files, read_state

            if not args.dry_run:
                stage.name = "lock"
                lock(conn)
            stage.name = "read state"
            registered, open_records, db_keys = read_state(conn)
            stage.name = "read files"
            files = new_files(raw_dir, registered)
            stage.name = "validate"
            results = transform(files, open_records, db_keys, existing_rows(conn))
            conn.rollback()
        n_files = sum(len(v) for v in files.values())
        n_open = sum(r.rechecked for r in results.values())
        print(f"transform ok in {time.perf_counter() - t0:.1f}s ({n_files} new files, {n_open} quarantine rows rechecked)")
        run_id = None
        if not args.dry_run:
            from .load import load

            stage.name = "load"
            run_id = str(load(conn, results, args.trigger, _git_version()))
    finally:
        if conn is not None:
            conn.close()  # also releases the advisory lock
    return results, run_id


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["fix"]:  # .\astra fix ...
        from .fix import main as fix_main

        return fix_main(argv[1:])
    if argv[:1] == ["notify"]:  # .\astra notify ...
        from .notify import main as notify_main

        return notify_main(argv[1:])
    if argv[:1] == ["etl"]:  # .\astra etl ...
        argv = argv[1:]
    ap = argparse.ArgumentParser(prog="astra etl")
    ap.add_argument("--dry-run", action="store_true", help="validate only, no database writes")
    ap.add_argument("--offline", action="store_true", help="with --dry-run: no database, every file is new")
    ap.add_argument("--trigger", default="MANUAL", choices=["MANUAL", "SCHEDULED", "REPROCESS"])
    ap.add_argument("--no-notify", action="store_true", help="do not send Telegram alerts for this load")
    args = ap.parse_args(argv)
    if args.offline and not args.dry_run:
        ap.error("--offline needs --dry-run")

    t0 = time.perf_counter()
    notify = not (args.dry_run or args.no_notify)
    stage = _Stage()
    try:
        results, run_id = _run(args, t0, stage)
    except Exception as e:
        if notify:
            from .notify import client_from_env, deliver, failure_alert

            deliver([failure_alert(stage.name, e, args.trigger)], client_from_env())
        raise
    summary = write_summary(results, "dry-run" if args.dry_run else "load", run_id)
    for spec in SPECS if args.dry_run else ():  # a load already logged these lines
        r = results[spec.name]
        print(f"  {spec.name:20} files={len(r.files)} loaded={len(r.rows):>7} graduated={len(r.graduated):>5} "
              f"in_quarantine={len(r.quarantined):>5} duplicate={len(r.duplicates):>4}")
    if notify:
        from .notify import client_from_env, deliver, load_policy, run_alerts

        client = client_from_env()
        if client is None:
            print("Telegram alerts off (not set up in .env)")
        else:
            alerts = run_alerts(summary, args.trigger, time.perf_counter() - t0, load_policy())
            print(f"alerts sent: {deliver(alerts, client)} of {len(alerts)}")
    print(f"done in {time.perf_counter() - t0:.1f}s; summary: reports/etl/last_run_summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
