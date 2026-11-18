"""Phase 11: spec test cases that had no direct test yet (docs/19-testing-and-validation.md maps all 17).

Offline: synthetic mini files and an in-memory stand-in for the database connection.
"""
import csv
import importlib
import pathlib
import sys
import types

import pytest

from astra_etl.transform import transform_dir

from .test_transform import HEADERS, ROWS

# load.py and db.connect import psycopg2, which the test venv does not have. A stub is enough:
# the tests below replace every psycopg2 function that would touch a database.
if importlib.util.find_spec("psycopg2") is None:
    _pg = types.ModuleType("psycopg2")
    _extras = types.ModuleType("psycopg2.extras")
    _extras.Json = lambda value: value
    _extras.execute_values = lambda *a, **k: None
    _pg.extras = _extras
    _pg.connect = lambda **kw: (_ for _ in ()).throw(AssertionError("no real connection in tests"))
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _extras

from astra_etl import __main__ as etl_main  # noqa: E402
from astra_etl import db, load, notify  # noqa: E402


def _write(raw: pathlib.Path, rows: dict | None = None) -> pathlib.Path:
    raw.mkdir(parents=True, exist_ok=True)
    data = {**ROWS, **(rows or {})}
    for t, header in HEADERS.items():
        with (raw / f"{t}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(data[t])
    return raw


def _rules(result) -> dict:
    return {q.record_key: (q.rule_id, q.issue_code, q.failed_columns) for q in result.quarantined}


# --- case 2: empty source file ------------------------------------------------------------------

def test_header_only_file_reads_zero_rows(tmp_path):
    r = transform_dir(_write(tmp_path))                # service_orders etc. have a header and no rows
    (f,) = r["service_orders"].files
    assert (f.rows_read, f.rows_loaded, f.rows_quarantined, f.rows_duplicate) == (0, 0, 0, 0)
    assert not r["service_orders"].rows and not r["service_orders"].quarantined


def test_zero_byte_file_stops_with_a_clear_error(tmp_path):
    raw = _write(tmp_path)
    (raw / "attendance.csv").write_bytes(b"")
    with pytest.raises(RuntimeError, match=r"attendance\.csv: missing columns"):
        transform_dir(raw)


# --- cases 4, 5, 7, 9: required field, invalid date, inconsistent category, invalid status ------

BAD_ROWS = {
    "products": ROWS["products"] + [
        ["PRD00003", "N/A", "Autoparts", "pcs", "100", "80", "Y"],           # 4 required field (placeholder)
        ["PRD00004", "filter", "  autoPARTS ", " Pcs", "100", "80", "y"],    # 7 messy spelling -> canonical
        ["PRD00005", "lamp", "Spareparts", "pcs", "100", "80", "Y"],         # 7 outside the allowed set
    ],
    "sales_transactions": ROWS["sales_transactions"] + [
        ["SAL00000006", "2024-02-30", "", "PRD00001", "", "Sunter", "1", "1000", "0", "cash", "completed"],  # 5
        ["SAL00000007", "31/31/2024", "", "PRD00001", "", "Sunter", "1", "1000", "0", "cash", "completed"],  # 5
        ["SAL00000008", "2024-03-01", "", "PRD00001", "", "Sunter", "1", "1000", "0", "cash", "shipped"],    # 9
    ],
}


def test_required_date_category_and_status_rules(tmp_path):
    r = transform_dir(_write(tmp_path, BAD_ROWS))
    prd = _rules(r["products"])
    assert prd["PRD00003"] == ("REQUIRED_FIELD_MISSING", "MISSING_REQUIRED_FIELD", ["product_name"])
    assert prd["PRD00005"] == ("CATEGORY_VALUE_INVALID", "INVALID_CATEGORY", ["product_category"])
    ok = {x.row["product_id"]: x.row for x in r["products"].rows}
    assert (ok["PRD00004"]["product_category"], ok["PRD00004"]["unit_of_measure"]) == ("AUTOPARTS", "PCS")

    sales = _rules(r["sales_transactions"])
    assert sales["SAL00000006"] == ("DATE_FORMAT_INVALID", "INVALID_DATE_FORMAT", ["transaction_date"])
    assert sales["SAL00000007"] == ("DATE_FORMAT_INVALID", "INVALID_DATE_FORMAT", ["transaction_date"])
    assert sales["SAL00000008"] == ("CATEGORY_VALUE_INVALID", "INVALID_CATEGORY", ["transaction_status"])
    loaded = {x.row["transaction_id"] for x in r["sales_transactions"].rows}
    assert not loaded & {"SAL00000006", "SAL00000007", "SAL00000008"}   # never loaded


# --- case 10: PostgreSQL connection failure -----------------------------------------------------

class _Alerts:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


def test_connection_failure_alerts_stage_only_and_reraises(monkeypatch):
    class OperationalError(Exception):
        pass

    def refuse(role):
        raise OperationalError("could not connect to server at db.internal.example port 5432")

    alerts = _Alerts()
    monkeypatch.setattr(etl_main, "connect", refuse)
    monkeypatch.setattr(notify, "client_from_env", lambda log=print: alerts)
    with pytest.raises(OperationalError):
        etl_main.main(["etl"])
    (text,) = alerts.sent
    assert "stage: connect" in text and "OperationalError" in text
    assert "db.internal.example" not in text and "5432" not in text   # no host or message details


def test_connect_rejects_bad_project_ref_before_any_network_call(monkeypatch):
    calls = []
    monkeypatch.setattr(db, "load_env", lambda: {"SUPABASE_PROJECT_REF": "short"})
    monkeypatch.setattr(sys.modules["psycopg2"], "connect", lambda **kw: calls.append(kw))
    with pytest.raises(RuntimeError, match="20-char project ref"):
        db.connect("analyst")
    assert not calls


# --- case 12: interrupted load -----------------------------------------------------------------

class _Cursor:
    def __init__(self, conn):
        self.conn, self.rowcount = conn, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.log.append(("sql", " ".join(sql.split())[:60], params))
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise ConnectionResetError("server closed the connection unexpectedly")
        if isinstance(params, dict) and "ids" in params:
            self.rowcount = len(params["ids"])

    def fetchone(self):
        return ("run-1",)


class _Conn:
    def __init__(self, fail_on=None):
        self.fail_on, self.log = fail_on, []

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))


def _fake_execute_values(cur, sql, data, template=None, page_size=None):
    cur.execute(sql, list(data))


def test_interrupted_load_rolls_back_and_marks_run_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(load, "execute_values", _fake_execute_values)
    results = transform_dir(_write(tmp_path))
    conn = _Conn(fail_on="INSERT INTO dataset.sales_transactions")
    with pytest.raises(ConnectionResetError):
        load.load(conn, results, "MANUAL", None, log=lambda *a: None)

    events = [e[0] if e[0] != "sql" else e[1] for e in conn.log]
    assert events[0].startswith("INSERT INTO dataset.etl_run") and events[1] == "commit"   # RUNNING row visible
    i_customers = next(i for i, e in enumerate(events) if e.startswith("INSERT INTO dataset.customers"))
    i_rollback = events.index("rollback")
    assert i_customers < i_rollback and "commit" not in events[2:i_rollback]  # earlier tables are rolled back too
    failed = [e for e in conn.log if e[0] == "sql" and "status = 'FAILED'" in e[1]]
    assert failed and failed[0][2][0] == "error: ConnectionResetError"         # error class only
    assert events[-1] == "commit"
    assert not any(e[0] == "sql" and "status = 'SUCCEEDED'" in e[1] for e in conn.log)


def test_completed_load_commits_once_after_all_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(load, "execute_values", _fake_execute_values)
    conn = _Conn()
    assert load.load(conn, transform_dir(_write(tmp_path)), "MANUAL", None, log=lambda *a: None) == "run-1"
    events = [e[0] if e[0] != "sql" else e[1] for e in conn.log]
    assert events.count("commit") == 2 and "rollback" not in events
    assert events[-2].startswith("UPDATE dataset.etl_run SET status = 'SUCCEEDED'")


# --- case 13: duplicate rerun --------------------------------------------------------------------

def test_rerun_skips_loaded_files_and_refuses_changed_ones(tmp_path):
    raw = _write(tmp_path)
    first = load.new_files(raw, {}, log=lambda *a: None)
    registered = {(t, f.name): f.sha256 for t, fs in first.items() for f in fs}
    assert sum(len(v) for v in first.values()) == 10

    assert load.new_files(raw, registered, log=lambda *a: None) == {}   # same files again: nothing new

    (raw / "customers").mkdir()                                         # same content under a new name
    (raw / "customers" / "2026-11-19.csv").write_bytes((raw / "customers.csv").read_bytes())
    skipped = []
    assert load.new_files(raw, registered, log=skipped.append) == {}
    assert skipped and "same content as a file already loaded" in skipped[0]

    with (raw / "products.csv").open("a", encoding="utf-8", newline="") as f:   # a loaded file was edited
        f.write("PRD00009,cap,Autoparts,pcs,1,1,Y\r\n")
    with pytest.raises(RuntimeError, match="changed after it was loaded"):
        load.new_files(raw, registered, log=lambda *a: None)


# --- case 15: validation-only execution ---------------------------------------------------------

def test_dry_run_offline_never_connects_or_alerts(tmp_path, monkeypatch):
    _write(tmp_path / "raw-data")
    alerts = _Alerts()
    monkeypatch.setattr(etl_main, "ROOT", tmp_path)
    monkeypatch.setattr(etl_main, "connect", lambda role: pytest.fail("dry run --offline must not connect"))
    monkeypatch.setattr(notify, "client_from_env", lambda log=print: alerts)
    assert etl_main.main(["etl", "--dry-run", "--offline"]) == 0
    summary = (tmp_path / "reports" / "etl" / "last_run_summary.md").read_text(encoding="utf-8")
    assert "ETL run summary (dry-run)" in summary and "n/a (dry run)" in summary
    assert not alerts.sent


def test_offline_needs_dry_run():
    with pytest.raises(SystemExit):
        etl_main.main(["etl", "--offline"])
