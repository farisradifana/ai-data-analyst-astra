"""Transform rules: duplicates (D5), quarantine, FK orphans, reconciliation. Synthetic mini files."""
import csv
import pathlib

from astra_etl.spec import SPECS
from astra_etl.transform import transform_dir as transform

HEADERS = {
    "customers": ["customer_id", "customer_name", "customer_type", "email", "phone", "city", "registration_date", "customer_status"],
    "employees": ["employee_id", "employee_name", "email", "department", "job_title", "branch", "hire_date", "employment_status", "monthly_salary", "manager_id"],
    "suppliers": ["supplier_id", "supplier_name", "contact_name", "email", "phone", "city", "payment_terms", "supplier_status"],
    "products": ["product_id", "product_name", "product_category", "unit_of_measure", "list_price", "standard_cost", "active_flag"],
    "sales_transactions": ["transaction_id", "transaction_date", "customer_id", "product_id", "employee_id", "branch", "quantity", "unit_price", "discount_pct", "payment_method", "transaction_status"],
    "service_orders": ["service_order_id", "service_date", "customer_id", "product_id", "technician_employee_id", "branch", "service_type", "labor_amount", "parts_amount", "service_status"],
    "procurement": ["procurement_id", "po_date", "supplier_id", "product_id", "buyer_employee_id", "quantity_ordered", "unit_cost", "expected_delivery_date", "po_status"],
    "inventory": ["inventory_id", "snapshot_date", "product_id", "warehouse_code", "quantity_on_hand", "reorder_point", "unit_cost", "stock_status"],
    "expenses": ["expense_id", "expense_date", "branch", "department", "submitted_by_employee_id", "expense_category", "amount", "approval_status", "vendor_name"],
    "attendance": ["attendance_id", "attendance_date", "employee_id", "branch", "check_in", "check_out", "attendance_status"],
}

ROWS = {
    "customers": [["CUS000001", "ani", "Individual", "N/A", "null", "N/A", "2024-01-02", "active"]],
    "employees": [
        ["EMP00001", "Budi", "", "Sales", "Sales Executive", "Sunter", "2020-01-01", "Active", "Rp 5,000,000", ""],
        ["EMP00002", "Cici", "", "Sales", "Sales Executive", "Sunter", "2020-01-01", "Active", "5000000", "EMP00001"],
        ["EMP00003", "Dedi", "", "Sales", "Sales Executive", "Sunter", "2020-01-01", "Active", "5000000", "EMP09999"],
        ["EMP00004", "Eko", "", "Sales", "Sales Executive", "Sunter", "2020-01-01", "Active", "5000000", "EMP00003"],
    ],
    "suppliers": [["SUP0001", "pt a", "x", "a@b.co", "0812", "Jakarta", "30 days", "Active"]],
    "products": [["PRD00001", "pad", "Autoparts", "pcs", "100", "80", "Y"],
                 ["PRD00002", "oil", "Autoparts", "pcs", "-5", "80", "Y"]],  # D4 -> quarantined
    "sales_transactions": [
        ["SAL00000001", "08/07/2024", "CUS000001", "PRD00001", "EMP00001", "Sunter", "2", "Rp 1,000", "10%", "cash", "completed"],
        ["SAL00000001", "08/07/2024", "CUS000001", "PRD00001", "EMP00001", "Sunter", "2", "Rp 1,000", "10%", "cash", "completed"],
        ["SAL00000002", "08/07/2024", "CUS999999", "PRD00001", "EMP00001", "Sunter", "1", "1000", "0", "cash", "completed"],
        ["SAL00000003", "08/07/2024", "", "PRD00001", "EMP00001", "Sunter", "two", "1000", "0", "cash", "completed"],
        ["SAL00000004", "08/07/2024", "", "", "", "Sunter", "1", "1000", "0", "cash", "pending"],
        ["SAL00000005", "08/07/2024", "", "PRD00002", "", "Sunter", "1", "1000", "0", "cash", "pending"],
    ],
    "service_orders": [], "procurement": [], "inventory": [], "expenses": [], "attendance": [],
}


def _write(tmp_path: pathlib.Path) -> pathlib.Path:
    for t, header in HEADERS.items():
        with (tmp_path / f"{t}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(ROWS[t])
    return tmp_path


def test_transform_rules(tmp_path):
    r = transform(_write(tmp_path))
    sales = r["sales_transactions"]
    assert len(sales.duplicates) == 1                      # D5 keep first
    assert [r.row["transaction_id"] for r in sales.rows] == ["SAL00000001", "SAL00000004"]
    rules = {q.record_key: (q.rule_id, q.issue_code, q.failed_columns, q.depends_on) for q in sales.quarantined}
    assert rules == {
        "SAL00000002": ("ORPHAN_KEY_NOT_IN_SOURCE", "ORPHAN_FOREIGN_KEY", ["customer_id"], None),
        "SAL00000003": ("NUMERIC_VALUE_INVALID", "INVALID_NUMERIC_VALUE", ["quantity"], None),
        "SAL00000005": ("ORPHAN_PARENT_QUARANTINED", "ORPHAN_FOREIGN_KEY", ["product_id"], "products:PRD00002"),
    }
    (dup,) = sales.duplicates
    assert (dup.rule_id, dup.record_key, dup.line, dup.depends_on) == ("EXACT_DUPLICATE_ROW", "SAL00000001", 3,
                                                                    "row:sales_transactions.csv:2")
    loaded = {r.row["transaction_id"]: r.row for r in sales.rows}
    assert loaded["SAL00000004"]["customer_id"] is None    # blank FK allowed
    assert str(loaded["SAL00000001"]["discount_pct"]) == "10.00"


def test_self_reference_cascades(tmp_path):
    emp = transform(_write(tmp_path))["employees"]
    assert sorted(r.row["employee_id"] for r in emp.rows) == ["EMP00001", "EMP00002"]
    rules = {q.record_key: (q.rule_id, q.depends_on) for q in emp.quarantined}
    assert rules == {"EMP00003": ("ORPHAN_KEY_NOT_IN_SOURCE", None),                   # manager absent
                     "EMP00004": ("ORPHAN_PARENT_QUARANTINED", "employees:EMP00003")}  # waits for 3


def test_parent_rule_and_raw_kept(tmp_path):
    r = transform(_write(tmp_path))
    (prd,) = r["products"].quarantined
    assert (prd.rule_id, prd.failed_columns) == ("NEGATIVE_AMOUNT", ["list_price"])
    orphan = next(q for q in r["sales_transactions"].quarantined if q.record_key == "SAL00000005")
    assert orphan.raw["product_id"] == "PRD00002" and orphan.raw["quantity"] == "1"  # original raw row


def test_quarantine_detail_has_no_values(tmp_path):
    sales = transform(_write(tmp_path))["sales_transactions"]
    for q in sales.quarantined:
        assert "CUS999999" not in q.issue_detail and "two" not in q.issue_detail
        assert q.raw  # original raw kept for reprocessing


def test_reconciliation_and_canonical_values(tmp_path):
    r = transform(_write(tmp_path))
    for spec in SPECS:
        (f,) = r[spec.name].files
        assert f.rows_loaded + f.rows_quarantined + f.rows_duplicate == f.rows_read
        assert f.name == f"{spec.name}.csv" and len(f.sha256) == 64
    (cust,) = [x.row for x in r["customers"].rows]
    assert cust["customer_name"] == "Ani" and cust["email"] is None and cust["city"] is None
    (sup,) = [x.row for x in r["suppliers"].rows]
    assert sup["payment_terms"] == "NET30"
