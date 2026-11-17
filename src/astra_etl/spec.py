"""Per-table mapping: raw CSV column -> cleaner -> dataset column. Load order respects FKs.

Closed sets mirror the CHECK constraints in sql/migrations/20261117090200_dataset_core_tables.sql.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Callable

from . import clean as c

BRANCHES = frozenset({"BANDUNG", "BEKASI", "CAKUNG", "SUNTER", "SURABAYA", "TANGERANG"})
DEPARTMENTS = frozenset({"AFTER SALES", "FINANCE", "HR", "PROCUREMENT", "SALES", "SERVICE", "WAREHOUSE"})


@dataclass(frozen=True)
class Column:
    target: str
    source: str
    cleaner: Callable[[str | None], Any]


@dataclass(frozen=True)
class TableSpec:
    name: str
    pk: str
    columns: tuple[Column, ...]
    # (column, parent table, nullable). Blank nullable FK -> NULL; unknown key -> ORPHAN_FOREIGN_KEY.
    fks: tuple[tuple[str, str, bool], ...] = field(default_factory=tuple)
    # Cross-column rules: (rule_id from astra_etl.rules, predicate(row) -> True when the row is valid)
    row_rules: tuple[tuple[str, Callable[[dict], bool]], ...] = field(default_factory=tuple)

    @property
    def file(self) -> str:
        return f"{self.name}.csv"


def _col(target: str, cleaner: Callable, source: str | None = None) -> Column:
    return Column(target, source or target, cleaner)


ident = c.identifier
opt_ident = partial(c.identifier, nullable=True)


SPECS: tuple[TableSpec, ...] = (
    TableSpec("customers", "customer_id", (
        _col("customer_id", ident),
        _col("customer_name", c.name),
        _col("customer_type", partial(c.code, allowed={"CORPORATE", "INDIVIDUAL"})),
        _col("email", c.email),
        _col("phone", c.phone),
        _col("city", lambda v: (c.optional(v) or "").upper() or None),
        _col("registration_date", c.date),
        _col("customer_status", partial(c.code, allowed={"ACTIVE", "INACTIVE"})),
    )),
    TableSpec("employees", "employee_id", (
        _col("employee_id", ident),
        _col("employee_name", c.name),
        _col("email", c.email),
        _col("department", partial(c.code, allowed=DEPARTMENTS)),
        _col("job_title", lambda v: c.required(v).upper()),
        _col("branch", partial(c.code, allowed=BRANCHES)),
        _col("hire_date", c.date),
        _col("employment_status", partial(c.code, allowed={"ACTIVE", "ON LEAVE", "RESIGNED"})),
        _col("monthly_salary", c.money),
        _col("manager_id", opt_ident),  # D6: blank allowed
    ), fks=(("manager_id", "employees", True),),
       row_rules=(("MANAGER_IS_SELF", lambda r: r["manager_id"] != r["employee_id"]),)),
    TableSpec("suppliers", "supplier_id", (
        _col("supplier_id", ident),
        _col("supplier_name", c.name),
        _col("contact_name", partial(c.name, nullable=True)),
        _col("email", c.email),
        _col("phone", c.phone),
        _col("city", lambda v: (c.optional(v) or "").upper() or None),
        _col("payment_terms", c.payment_terms),
        _col("supplier_status", partial(c.code, allowed={"ACTIVE", "INACTIVE"})),
    )),
    TableSpec("products", "product_id", (
        _col("product_id", ident),
        _col("product_name", c.name),
        _col("product_category", partial(c.code, allowed={"ASTRAMOBIL", "AUTOPARTS", "FLEETCARE", "MOTOPRIMA", "POWERGEN"})),
        _col("unit_of_measure", partial(c.code, allowed={"LITER", "PCS", "SET", "UNIT"})),
        _col("list_price", c.money),
        _col("standard_cost", c.money),
        _col("is_active", c.flag, source="active_flag"),
    )),
    TableSpec("sales_transactions", "transaction_id", (
        _col("transaction_id", ident),
        _col("transaction_date", c.date),
        _col("customer_id", opt_ident),
        _col("product_id", opt_ident),
        _col("employee_id", opt_ident),
        _col("branch", partial(c.code, allowed=BRANCHES)),
        _col("quantity", partial(c.integer, min_value=1)),  # D3
        _col("unit_price", c.money),
        _col("discount_pct", c.percent),
        _col("payment_method", partial(c.code, allowed={"CASH", "CREDIT CARD", "LEASING", "TRANSFER"})),
        _col("transaction_status", partial(c.code, allowed={"CANCELLED", "COMPLETED", "PENDING"})),
    ), fks=(("customer_id", "customers", True), ("product_id", "products", True),
            ("employee_id", "employees", True))),
    TableSpec("service_orders", "service_order_id", (
        _col("service_order_id", ident),
        _col("service_date", c.date),
        _col("customer_id", opt_ident),
        _col("product_id", opt_ident),
        _col("technician_employee_id", opt_ident),
        _col("branch", partial(c.code, allowed=BRANCHES)),
        _col("service_type", partial(c.code, allowed={"INSPECTION", "INSTALLATION", "PERIODIC MAINTENANCE", "REPAIR"})),
        _col("labor_amount", c.money),
        _col("parts_amount", c.money),
        _col("service_status", partial(c.code, allowed={"CANCELLED", "COMPLETED", "OPEN"})),
    ), fks=(("customer_id", "customers", True), ("product_id", "products", True),
            ("technician_employee_id", "employees", True))),
    TableSpec("procurement", "procurement_id", (
        _col("procurement_id", ident),
        _col("po_date", c.date),
        _col("supplier_id", opt_ident),
        _col("product_id", opt_ident),
        _col("buyer_employee_id", opt_ident),
        _col("quantity_ordered", partial(c.integer, min_value=1)),
        _col("unit_cost", c.money),
        _col("expected_delivery_date", c.date),
        _col("po_status", partial(c.code, allowed={"CANCELLED", "OPEN", "PARTIAL", "RECEIVED"})),
    ), fks=(("supplier_id", "suppliers", True), ("product_id", "products", True),
            ("buyer_employee_id", "employees", True))),
    TableSpec("inventory", "inventory_id", (
        _col("inventory_id", ident),
        _col("snapshot_date", c.date),
        _col("product_id", ident),
        _col("warehouse_code", lambda v: c.required(v).upper()),
        _col("quantity_on_hand", partial(c.integer, min_value=0)),
        _col("reorder_point", partial(c.integer, min_value=0)),
        _col("unit_cost", c.money),
        _col("stock_status", partial(c.code, allowed={"AVAILABLE", "LOW STOCK", "RESERVED"})),
    ), fks=(("product_id", "products", False),),
       row_rules=(("WAREHOUSE_CODE_FORMAT", lambda r: bool(re.fullmatch(r"WH-[A-Z]{3}-\d{2}", r["warehouse_code"]))),)),
    TableSpec("expenses", "expense_id", (
        _col("expense_id", ident),
        _col("expense_date", c.date),
        _col("branch", partial(c.code, allowed=BRANCHES)),
        _col("department", partial(c.code, allowed=DEPARTMENTS)),
        _col("submitted_by_employee_id", ident),
        _col("expense_category", partial(c.code, allowed={"MAINTENANCE", "MARKETING", "OFFICE SUPPLIES", "TRAINING", "TRAVEL", "UTILITIES"})),
        _col("amount", c.money),  # D4: negative -> BUSINESS_RULE_VIOLATION
        _col("approval_status", partial(c.code, allowed={"APPROVED", "PENDING", "REJECTED"})),
        _col("vendor_name", c.name),
    ), fks=(("submitted_by_employee_id", "employees", False),)),
    TableSpec("attendance", "attendance_id", (
        _col("attendance_id", ident),
        _col("attendance_date", c.date),
        _col("employee_id", ident),
        _col("branch", partial(c.code, allowed=BRANCHES)),
        _col("check_in", c.time),
        _col("check_out", c.time),
        _col("attendance_status", partial(c.code, allowed={"ABSENT", "LATE", "LEAVE", "PRESENT"})),
    ), fks=(("employee_id", "employees", False),),
       row_rules=(("CHECKOUT_BEFORE_CHECKIN",
                   lambda r: r["check_in"] is None or r["check_out"] is None or r["check_out"] >= r["check_in"]),)),
)

SPEC_BY_NAME = {s.name: s for s in SPECS}
