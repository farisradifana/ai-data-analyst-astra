"""Quarantine rule catalog. Every quarantined or duplicate row carries exactly one rule_id.

Mirrors table dataset.quarantine_rule (latest seed in
sql/migrations/20261118120000_live_quarantine.sql); tests/etl/test_rules.py keeps them in sync.

graduation_path says how a quarantined row becomes valid data:
  FIX_IN_QUARANTINE  edit the value in the quarantine row (astra fix set); the next ETL run
                     rechecks it, loads it, archives it as GRADUATED and removes it from quarantine.
  AUTO_WITH_PARENT   nothing to fix on this row; it graduates on the run its parent row
                     (see depends_on) graduates.
  NOT_NEEDED         exact copy of a row already loaded or held; never loaded, archived as
                     DUPLICATE_DROPPED.
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
    Rule("REQUIRED_FIELD_MISSING", "MISSING_REQUIRED_FIELD", None, "FIX_IN_QUARANTINE",
         "Required value is blank or a placeholder (N/A, NA, NULL, NONE, -, UNKNOWN, TBD).",
         "Fill in the real value with astra fix set; the next ETL run rechecks the row."),
    Rule("DATE_FORMAT_INVALID", "INVALID_DATE_FORMAT", "D1", "FIX_IN_QUARANTINE",
         "Date or time is not in an accepted format or is not a real calendar date.",
         "Set the date as YYYY-MM-DD (time as HH:MM) with astra fix set."),
    Rule("NUMERIC_VALUE_INVALID", "INVALID_NUMERIC_VALUE", "D3", "FIX_IN_QUARANTINE",
         "Number cannot be parsed, is a word, or is out of range (quantity <= 0, percent outside 0-100).",
         "Set a valid number in range with astra fix set."),
    Rule("CATEGORY_VALUE_INVALID", "INVALID_CATEGORY", None, "FIX_IN_QUARANTINE",
         "Value is outside the allowed set, or an identifier has an invalid format.",
         "Set one of the allowed values (docs/30-database-schema.md) with astra fix set."),
    Rule("NEGATIVE_AMOUNT", "BUSINESS_RULE_VIOLATION", "D4", "FIX_IN_QUARANTINE",
         "Money amount (price, cost, salary, expense) is negative.",
         "Set the correct non-negative amount with astra fix set. Refunds need their own record type."),
    Rule("MANAGER_IS_SELF", "BUSINESS_RULE_VIOLATION", None, "FIX_IN_QUARANTINE",
         "Employee is listed as their own manager.",
         "Set the correct manager_id, or blank it (D6), with astra fix set."),
    Rule("WAREHOUSE_CODE_FORMAT", "INVALID_CATEGORY", None, "FIX_IN_QUARANTINE",
         "Warehouse code does not match WH-AAA-00.",
         "Set a code like WH-AAA-00 with astra fix set."),
    Rule("CHECKOUT_BEFORE_CHECKIN", "BUSINESS_RULE_VIOLATION", None, "FIX_IN_QUARANTINE",
         "Attendance check_out is earlier than check_in.",
         "Correct check_in or check_out with astra fix set."),
    Rule("DUPLICATE_PRIMARY_KEY", "DUPLICATE_PRIMARY_KEY", "D5", "FIX_IN_QUARANTINE",
         "Same primary key as a row already loaded (earlier in the file or from an earlier file) but different content.",
         "Give this row its own key with astra fix set, or remove it with astra fix drop if the loaded row is correct."),
    Rule("ORPHAN_PARENT_QUARANTINED", "ORPHAN_FOREIGN_KEY", None, "AUTO_WITH_PARENT",
         "Referenced parent row is itself in quarantine.",
         "Fix the parent named in depends_on; this row graduates on the same run."),
    Rule("ORPHAN_KEY_NOT_IN_SOURCE", "ORPHAN_FOREIGN_KEY", None, "FIX_IN_QUARANTINE",
         "Referenced key is not loaded and not in quarantine.",
         "Graduates by itself when a later file brings the parent; otherwise correct or blank the key with astra fix set."),
    Rule("EXACT_DUPLICATE_ROW", "EXACT_DUPLICATE_ROW", "D5", "NOT_NEEDED",
         "Exact copy of a row already loaded or already in quarantine.",
         "No action. Not loaded; archived as DUPLICATE_DROPPED."),
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
