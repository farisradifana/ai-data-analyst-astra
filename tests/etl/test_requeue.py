"""Live quarantine: rows are fixed inside quarantine and rechecked on every run; new files are read once."""
import csv
import itertools

from astra_etl.spec import SPEC_BY_NAME, SPECS
from astra_etl.transform import OpenRecord, SourceFile, discover, transform, transform_dir

from .test_transform import HEADERS, _write


class Db:
    """In-memory stand-in for the database after a load."""

    def __init__(self, results):
        self.keys = {t: r.loaded_keys() for t, r in results.items()}
        self.rows = {t: {x.row[r.spec.pk]: tuple(x.row[c.target] for c in r.spec.columns) for x in r.rows}
                     for t, r in results.items()}
        ids = itertools.count(1)
        self.open = {t: [OpenRecord(next(ids), q.source_file, q.line, dict(q.raw)) for q in r.quarantined]
                     for t, r in results.items()}

    def existing(self, table, keys):
        return {k: self.rows[table][k] for k in keys if k in self.rows[table]}

    def record(self, table, key):
        return next(o for o in self.open[table] if o.raw[SPEC_BY_NAME[table].pk] == key)

    def run(self, files=None):
        return transform(files or {}, self.open, self.keys, self.existing)


def _file(table, name, rows):
    return SourceFile(table, name, "0" * 64, tuple((i + 2, dict(zip(HEADERS[table], row))) for i, row in enumerate(rows)))


def _first_load(tmp_path):
    return Db(transform_dir(_write(tmp_path)))


def _check_reconciliation(results):
    for r in results.values():
        dropped = sum(1 for q in r.duplicates if q.quarantine_id is not None)
        assert len(r.graduated) + len(r.still_open) + dropped == r.rechecked
        for f in r.files:
            assert f.rows_loaded + f.rows_quarantined + f.rows_duplicate == f.rows_read


def test_rerun_without_edits_changes_nothing(tmp_path):
    db = _first_load(tmp_path)
    r = db.run()
    for spec in SPECS:
        res = r[spec.name]
        assert not res.rows and not res.files
        assert len(res.still_open) == res.rechecked == len(db.open[spec.name])
    _check_reconciliation(r)


def test_edited_parent_graduates_with_its_children(tmp_path):
    db = _first_load(tmp_path)
    prd = db.record("products", "PRD00002")
    prd.raw["list_price"] = "Rp 50,000"
    r = db.run()
    assert r["products"].graduated == [prd.quarantine_id]
    assert [x.row["product_id"] for x in r["products"].rows] == ["PRD00002"]
    sal5 = db.record("sales_transactions", "SAL00000005")
    assert sal5.quarantine_id in r["sales_transactions"].graduated      # waited for PRD00002
    still = {q.record_key: q.rule_id for q in r["sales_transactions"].still_open}
    assert still == {"SAL00000002": "ORPHAN_KEY_NOT_IN_SOURCE", "SAL00000003": "NUMERIC_VALUE_INVALID"}
    _check_reconciliation(r)


def test_bad_edit_stays_with_new_label(tmp_path):
    db = _first_load(tmp_path)
    rec = db.record("sales_transactions", "SAL00000003")
    rec.raw["quantity"] = ""
    r = db.run()
    q = next(q for q in r["sales_transactions"].still_open if q.quarantine_id == rec.quarantine_id)
    assert (q.rule_id, q.failed_columns) == ("REQUIRED_FIELD_MISSING", ["quantity"])


def test_new_file_key_already_loaded_is_strict(tmp_path):
    db = _first_load(tmp_path)
    same = ["SAL00000001", "08/07/2024", "CUS000001", "PRD00001", "EMP00001", "Sunter", "2", "Rp 1,000", "10%", "cash", "completed"]
    other = ["SAL00000004", "09/07/2024", "", "", "", "Sunter", "3", "1000", "0", "cash", "pending"]
    fresh = ["SAL00000010", "09/07/2024", "", "PRD00001", "", "Sunter", "3", "1000", "0", "cash", "pending"]
    day = _file("sales_transactions", "sales_transactions/2026-11-19.csv", [same, other, fresh])
    sales = db.run({"sales_transactions": [day]})["sales_transactions"]
    assert [x.row["transaction_id"] for x in sales.rows] == ["SAL00000010"]
    (dup,) = sales.duplicates
    assert (dup.rule_id, dup.depends_on, dup.quarantine_id) == ("EXACT_DUPLICATE_ROW", "sales_transactions:SAL00000001", None)
    clash = next(q for q in sales.new_quarantine if q.record_key == "SAL00000004")
    assert (clash.rule_id, clash.depends_on) == ("DUPLICATE_PRIMARY_KEY", "sales_transactions:SAL00000004")
    (f,) = sales.files
    assert (f.rows_read, f.rows_loaded, f.rows_quarantined, f.rows_duplicate) == (3, 1, 1, 1)


def test_missing_parent_arrives_in_a_later_file(tmp_path):
    db = _first_load(tmp_path)
    cust = _file("customers", "customers/2026-11-19.csv",
                 [["CUS999999", "budi", "Individual", "", "", "", "2024-01-03", "active"]])
    emp = _file("employees", "employees/2026-11-19.csv",
                [["EMP09999", "Fajar", "", "Sales", "Sales Manager", "Sunter", "2019-01-01", "Active", "9000000", ""]])
    r = db.run({"customers": [cust], "employees": [emp]})
    assert db.record("sales_transactions", "SAL00000002").quarantine_id in r["sales_transactions"].graduated
    graduated_emp = {x.row["employee_id"] for x in r["employees"].rows if x.quarantine_id}
    assert graduated_emp == {"EMP00003", "EMP00004"}                  # self-reference cascade
    assert not r["employees"].quarantined
    _check_reconciliation(r)


def test_edit_that_matches_a_loaded_row_is_dropped_as_duplicate(tmp_path):
    db = _first_load(tmp_path)
    rec = db.record("sales_transactions", "SAL00000003")
    rec.raw.update(transaction_id="SAL00000001", customer_id="CUS000001", quantity="2", unit_price="Rp 1,000",
                   discount_pct="10%")
    sales = db.run()["sales_transactions"]
    (dup,) = sales.duplicates
    assert (dup.quarantine_id, dup.rule_id) == (rec.quarantine_id, "EXACT_DUPLICATE_ROW")


def test_discover_reads_base_file_then_daily_files(tmp_path):
    _write(tmp_path)
    folder = tmp_path / "sales_transactions"
    folder.mkdir()
    for name in ("2026-11-20.csv", "2026-11-19.csv"):
        with (folder / name).open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(HEADERS["sales_transactions"])
    names = [n for n, _ in discover(tmp_path)["sales_transactions"]]
    assert names == ["sales_transactions.csv", "sales_transactions/2026-11-19.csv", "sales_transactions/2026-11-20.csv"]
