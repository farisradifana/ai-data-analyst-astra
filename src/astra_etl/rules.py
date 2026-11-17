"""Quarantine rule catalog. Every quarantined or duplicate row carries exactly one rule_id.

Mirrors table dataset.quarantine_rule (seeded in
sql/migrations/20261117100000_quarantine_rule_catalog.sql); tests/etl/test_rules.py keeps them in sync.

graduation_path says how a record becomes valid data:
  FIX_SOURCE        correct the value in the source file (raw-data/<table>.csv), then rerun the ETL.
  AUTO_WITH_PARENT  nothing to fix on this row; it loads on the next run once its parent row
                    (see depends_on) has graduated.
  NOT_NEEDED        exact copy of a row that already loaded; kept for audit only.
On the rerun, the old OPEN record becomes GRADUATED (row now loaded), SUPERSEDED (still failing;
a new OPEN record replaces it) or DISMISSED (row no longer in the source file).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    issue_code: str
    decision: str | None
    graduation_path: str
    description: str
    remediation: str


_RULES = (
    Rule("REQUIRED_FIELD_MISSING", "MISSING_REQUIRED_FIELD", None, "FIX_SOURCE",
         "Required value is blank or a placeholder (N/A, NA, NULL, NONE, -, UNKNOWN, TBD).",
         "Fill in the real value in the source file, then rerun the ETL."),
    Rule("DATE_FORMAT_INVALID", "INVALID_DATE_FORMAT", "D1", "FIX_SOURCE",
         "Date or time is not in an accepted format or is not a real calendar date.",
         "Write the date as YYYY-MM-DD (time as HH:MM), then rerun."),
    Rule("NUMERIC_VALUE_INVALID", "INVALID_NUMERIC_VALUE", "D3", "FIX_SOURCE",
         "Number cannot be parsed, is a word, or is out of range (quantity <= 0, percent outside 0-100).",
         "Enter a valid number in range, then rerun."),
    Rule("CATEGORY_VALUE_INVALID", "INVALID_CATEGORY", None, "FIX_SOURCE",
         "Value is outside the allowed set, or an identifier has an invalid format.",
         "Use one of the allowed values listed in docs/30-database-schema.md, then rerun."),
    Rule("NEGATIVE_AMOUNT", "BUSINESS_RULE_VIOLATION", "D4", "FIX_SOURCE",
         "Money amount (price, cost, salary, expense) is negative.",
         "Enter the correct non-negative amount, then rerun. Refunds need their own record type."),
    Rule("MANAGER_IS_SELF", "BUSINESS_RULE_VIOLATION", None, "FIX_SOURCE",
         "Employee is listed as their own manager.",
         "Set the correct manager_id, or leave it blank (D6), then rerun."),
    Rule("WAREHOUSE_CODE_FORMAT", "INVALID_CATEGORY", None, "FIX_SOURCE",
         "Warehouse code does not match WH-AAA-00.",
         "Correct the warehouse code, then rerun."),
    Rule("CHECKOUT_BEFORE_CHECKIN", "BUSINESS_RULE_VIOLATION", None, "FIX_SOURCE",
         "Attendance check_out is earlier than check_in.",
         "Correct the check-in or check-out time, then rerun."),
    Rule("DUPLICATE_PRIMARY_KEY", "DUPLICATE_PRIMARY_KEY", "D5", "FIX_SOURCE",
         "Same primary key as an earlier row but different content; the earlier row was loaded.",
         "Give this row its own key, or remove it if the earlier row is correct (see depends_on), then rerun."),
    Rule("ORPHAN_PARENT_QUARANTINED", "ORPHAN_FOREIGN_KEY", None, "AUTO_WITH_PARENT",
         "Referenced parent row exists in the source but is itself quarantined.",
         "Fix the parent row named in depends_on; this row graduates on the same rerun."),
    Rule("ORPHAN_KEY_NOT_IN_SOURCE", "ORPHAN_FOREIGN_KEY", None, "FIX_SOURCE",
         "Referenced key does not exist in the parent source file.",
         "Add the missing parent row, correct the key, or blank it if the column allows it, then rerun."),
    Rule("EXACT_DUPLICATE_ROW", "EXACT_DUPLICATE_ROW", "D5", "NOT_NEEDED",
         "Exact copy of an earlier row in the same file; the first copy was loaded.",
         "No action. Kept for audit; status is DISMISSED on insert."),
)

RULES: dict[str, Rule] = {r.rule_id: r for r in _RULES}

# Column-level CleanError code -> rule. Cross-column rules name their rule in spec.row_rules.
COLUMN_RULE = {
    "MISSING_REQUIRED_FIELD": "REQUIRED_FIELD_MISSING",
    "INVALID_DATE_FORMAT": "DATE_FORMAT_INVALID",
    "INVALID_NUMERIC_VALUE": "NUMERIC_VALUE_INVALID",
    "INVALID_CATEGORY": "CATEGORY_VALUE_INVALID",
    "BUSINESS_RULE_VIOLATION": "NEGATIVE_AMOUNT",  # only money() raises it at column level
}
