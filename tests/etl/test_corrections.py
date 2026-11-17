"""Corrections overlay: a fix stored in the database graduates the row on the next run."""
import copy
import csv

from astra_etl.transform import Correction, transform

from .test_transform import HEADERS, ROWS


def _write(tmp_path, extra_sales=()):
    rows = copy.deepcopy(ROWS)
    rows["sales_transactions"] += list(extra_sales)
    for t, header in HEADERS.items():
        with (tmp_path / f"{t}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows[t])
    return tmp_path


def fix(cid, table, key, column, value, line=None):
    return Correction(cid, table, key, line, column, value)


def test_fix_parent_graduates_children(tmp_path):
    r = transform(_write(tmp_path), [fix(1, "products", "prd00002", "list_price", "Rp 50,000")])
    assert "PRD00002" in {row["product_id"] for _, row in r["products"].rows}
    assert not r["products"].quarantined
    sales = {row["transaction_id"] for _, row in r["sales_transactions"].rows}
    assert "SAL00000005" in sales                      # waited for PRD00002, now loads
    assert r["products"].correction_outcome == {1: "LOADED"}


def test_bad_fix_stays_quarantined_and_is_labelled(tmp_path):
    r = transform(_write(tmp_path), [fix(1, "products", "PRD00002", "list_price", "-1")])
    (q,) = r["products"].quarantined
    assert (q.rule_id, q.corrected_columns, q.record_key) == ("NEGATIVE_AMOUNT", ["list_price"], "PRD00002")
    assert r["products"].correction_outcome == {1: "STILL_QUARANTINED"}


def test_unknown_key_and_column(tmp_path):
    r = transform(_write(tmp_path), [fix(1, "products", "PRD99999", "list_price", "1"),
                                     fix(2, "products", "PRD00002", "no_such_column", "1")])
    assert r["products"].correction_outcome == {1: "KEY_NOT_FOUND", 2: "COLUMN_UNKNOWN"}


def test_blank_value_and_fill_missing(tmp_path):
    # SAL00000003 has quantity "two" (D3); fill a real quantity.
    r = transform(_write(tmp_path), [fix(1, "sales_transactions", "SAL00000003", "quantity", "2")])
    loaded = dict((row["transaction_id"], row) for _, row in r["sales_transactions"].rows)
    assert loaded["SAL00000003"]["quantity"] == 2
    # NULL value blanks the cell: blank required quantity -> REQUIRED_FIELD_MISSING.
    r = transform(_write(tmp_path), [fix(1, "sales_transactions", "SAL00000004", "quantity", None)])
    q = next(q for q in r["sales_transactions"].quarantined if q.record_key == "SAL00000004")
    assert q.rule_id == "REQUIRED_FIELD_MISSING"


def test_line_scoped_key_change_for_duplicate_primary_key(tmp_path):
    conflict = ["SAL00000004", "09/07/2024", "", "", "", "Sunter", "3", "1000", "0", "cash", "pending"]  # line 8
    base = transform(_write(tmp_path, [conflict]))["sales_transactions"]
    (dup,) = [q for q in base.quarantined if q.rule_id == "DUPLICATE_PRIMARY_KEY"]
    assert dup.line == 8 and dup.depends_on == "row:6"

    r = transform(_write(tmp_path, [conflict]),
                  [fix(1, "sales_transactions", "SAL00000004", "transaction_id", "SAL00000009", line=8)])
    sales = r["sales_transactions"]
    assert {"SAL00000004", "SAL00000009"} <= {row["transaction_id"] for _, row in sales.rows}
    assert "SAL00000004" in sales.loaded_keys()        # old OPEN record (source key) -> GRADUATED
    assert sales.correction_outcome == {1: "LOADED"}


def test_reconciliation_holds_with_corrections(tmp_path):
    r = transform(_write(tmp_path), [fix(1, "products", "PRD00002", "list_price", "5")])
    for t in r.values():
        assert t.rows_loaded + len(t.quarantined) + t.rows_duplicate == t.rows_read
