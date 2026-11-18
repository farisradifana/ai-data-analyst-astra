# 06 — Data quality rules

Last checked: 2026-11-18

This page lists every validation rule the ETL applies and every quarantine reason code.
All data is synthetic. The code is the source of truth:
`src/astra_etl/clean.py` (value cleaners), `src/astra_etl/spec.py` (per-table mapping),
`src/astra_etl/rules.py` (rule catalog) and `src/astra_etl/transform.py` (check order).
The catalog is also stored in the table `dataset.quarantine_rule`
(last seeded by `sql/migrations/20261118120000_live_quarantine.sql`).
The test `tests/etl/test_rules.py` keeps the Python catalog and the SQL seed in sync.

How a quarantined row is fixed and loaded is in [doc 31](31-etl-and-quarantine.md).
The run itself is in [doc 07](07-etl-workflow.md). Table definitions are in [doc 30](30-database-schema.md).

## Order of checks

For each candidate row, `transform.py` runs these steps in order. The first step that fails decides the rule.

1. Exact copy of an earlier candidate in the same table (compared on raw values): `EXACT_DUPLICATE_ROW`.
2. Column cleaners. If any column fails, the rule comes from the first failing column (see the issue-code map below).
   `failed_columns` lists all failing columns.
3. Cross-column row rules (`MANAGER_IS_SELF`, `WAREHOUSE_CODE_FORMAT`, `CHECKOUT_BEFORE_CHECKIN`).
4. Same primary key as an earlier passing candidate in this run: `DUPLICATE_PRIMARY_KEY`.
5. Primary key already loaded in the database: same clean values give `EXACT_DUPLICATE_ROW`; different values give `DUPLICATE_PRIMARY_KEY` (strict keys, nothing is overwritten).
6. Foreign keys: parent loaded or passing in this run is fine; parent held in quarantine gives `ORPHAN_PARENT_QUARANTINED`; parent nowhere gives `ORPHAN_KEY_NOT_IN_SOURCE`.

A candidate is a row from a new source file, or a row already in quarantine (with analyst edits applied).
Tables run in dependency order (parents first): customers, employees, suppliers, products, sales_transactions, service_orders, procurement, inventory, expenses, attendance.

## Quarantine reason codes

Every quarantined or duplicate row carries exactly one `rule_id`.
The `issue_code` column is the older, coarser code that Laya and dashboards also use.

| rule_id | issue_code | Decision | Graduation path | Condition |
|---|---|---|---|---|
| `REQUIRED_FIELD_MISSING` | `MISSING_REQUIRED_FIELD` | none | `FIX_IN_QUARANTINE` | Required value is blank or a placeholder (`N/A`, `NA`, `NULL`, `NONE`, `-`, `UNKNOWN`, `TBD`, or empty) |
| `DATE_FORMAT_INVALID` | `INVALID_DATE_FORMAT` | D1 | `FIX_IN_QUARANTINE` | Date or time is not in an accepted format, or is not a real calendar date |
| `NUMERIC_VALUE_INVALID` | `INVALID_NUMERIC_VALUE` | D3 | `FIX_IN_QUARANTINE` | Number cannot be parsed, is a word, or is out of range (integer below its minimum, percent outside 0-100) |
| `CATEGORY_VALUE_INVALID` | `INVALID_CATEGORY` | none | `FIX_IN_QUARANTINE` | Value is outside the allowed set, or an identifier does not match `[A-Z0-9-]{1,32}` |
| `NEGATIVE_AMOUNT` | `BUSINESS_RULE_VIOLATION` | D4 | `FIX_IN_QUARANTINE` | Money amount (price, cost, salary, expense, labor, parts) is negative |
| `MANAGER_IS_SELF` | `BUSINESS_RULE_VIOLATION` | none | `FIX_IN_QUARANTINE` | `employees.manager_id` equals `employee_id` |
| `WAREHOUSE_CODE_FORMAT` | `INVALID_CATEGORY` | none | `FIX_IN_QUARANTINE` | `inventory.warehouse_code` does not match `WH-AAA-00` (three letters, two digits) |
| `CHECKOUT_BEFORE_CHECKIN` | `BUSINESS_RULE_VIOLATION` | none | `FIX_IN_QUARANTINE` | `attendance.check_out` is earlier than `check_in` (checked only when both are present) |
| `DUPLICATE_PRIMARY_KEY` | `DUPLICATE_PRIMARY_KEY` | D5 | `FIX_IN_QUARANTINE` | Same key as a loaded row or an earlier row in the run, but different content |
| `ORPHAN_PARENT_QUARANTINED` | `ORPHAN_FOREIGN_KEY` | none | `AUTO_WITH_PARENT` | Every missing parent of the row is itself in quarantine; the row graduates on the run its parent graduates |
| `ORPHAN_KEY_NOT_IN_SOURCE` | `ORPHAN_FOREIGN_KEY` | none | `FIX_IN_QUARANTINE` | A referenced key is neither loaded nor in quarantine. It also graduates by itself if a later file brings the parent |
| `EXACT_DUPLICATE_ROW` | `EXACT_DUPLICATE_ROW` | D5 | `NOT_NEEDED` | Exact copy of a row already loaded or already held. Never loaded; archived as `DUPLICATE_DROPPED` |

Map from the cleaner's error code to the rule (`rules.COLUMN_RULE`):

| Cleaner error | rule_id |
|---|---|
| `MISSING_REQUIRED_FIELD` | `REQUIRED_FIELD_MISSING` |
| `INVALID_DATE_FORMAT` | `DATE_FORMAT_INVALID` |
| `INVALID_NUMERIC_VALUE` | `NUMERIC_VALUE_INVALID` |
| `INVALID_CATEGORY` | `CATEGORY_VALUE_INVALID` |
| `BUSINESS_RULE_VIOLATION` | `NEGATIVE_AMOUNT` (only `money()` raises it at column level) |

Other labels on every quarantine row:
- `failed_columns`: target column names only, never values.
- `issue_detail`: `column:CODE` pairs, at most 500 characters, never values.
- `depends_on`: `<parent_table>:<key>`, or `row:<file>:<line>` for a duplicate, at most 100 characters.

Where each label is stored: table `dataset.quarantine_record` (live rows) and `dataset.quarantine_archive` (rows that left).
See [doc 09](09-postgresql-documentation.md).

## Value cleaners (`clean.py`)

| Cleaner | Accepts | Fails with |
|---|---|---|
| placeholder check | Trims and collapses spaces. Blank, `N/A`, `NA`, `NULL`, `NONE`, `-`, `UNKNOWN`, `TBD` (any case) count as blank | n/a |
| `required` | Trimmed text | `MISSING_REQUIRED_FIELD` |
| `identifier` | Upper-case, `[A-Z0-9-]{1,32}`. Optional variant: blank becomes NULL | `MISSING_REQUIRED_FIELD`, `INVALID_CATEGORY` |
| `code` | Upper-cased value that is in the closed set. Optional variant: blank becomes NULL | `MISSING_REQUIRED_FIELD`, `INVALID_CATEGORY` |
| `name` | Trimmed, Title Case. Optional variant: blank becomes NULL | `MISSING_REQUIRED_FIELD` |
| `date` (D1) | `YYYY-MM-DD`, `YYYY/MM/DD`, `DD/MM/YYYY`, `MM-DD-YYYY` | blank: `MISSING_REQUIRED_FIELD`; other text or impossible date: `INVALID_DATE_FORMAT` |
| `time` | `08:00`, `08.15`, `8:30 AM`, `5:00 PM`. Blank becomes NULL | `INVALID_DATE_FORMAT` |
| `money` (D4) | Number with optional `Rp` prefix, commas and spaces; stored with 2 decimals | blank: `MISSING_REQUIRED_FIELD`; not a number: `INVALID_NUMERIC_VALUE`; negative: `BUSINESS_RULE_VIOLATION` |
| `integer` (D3) | Whole number at or above the column minimum. Words such as `two` are not guessed | `MISSING_REQUIRED_FIELD`, `INVALID_NUMERIC_VALUE` |
| `percent` | `10` or `10%`, between 0 and 100 inclusive | `INVALID_NUMERIC_VALUE` |
| `flag` | `Y`, `YES`, `1`, `TRUE` give true; `N`, `NO`, `0`, `FALSE` give false | empty: `MISSING_REQUIRED_FIELD`; other: `INVALID_CATEGORY` |
| `payment_terms` (D2) | `COD`, `NET30`, `NET 30`, `30 DAYS`; the last three become `NET30` | `MISSING_REQUIRED_FIELD`, `INVALID_CATEGORY` |
| `email` | Lower-cased valid address | never fails: blank or invalid format becomes NULL |
| `phone` | Digits, `+`, `-`, spaces, 6 to 32 characters | never fails: blank, all-9 placeholder or bad format becomes NULL |

## Column rules by table (`spec.py`)

Source column names equal the target column unless noted. "Optional" means a blank becomes NULL and does not quarantine.

| Table | Primary key | Column rules | Foreign keys | Row rules |
|---|---|---|---|---|
| `customers` | `customer_id` | `customer_name` required; `customer_type` in CORPORATE, INDIVIDUAL; `email`, `phone`, `city` optional; `registration_date` date; `customer_status` in ACTIVE, INACTIVE | none | none |
| `employees` | `employee_id` | `employee_name` required; `email` optional; `department` in AFTER SALES, FINANCE, HR, PROCUREMENT, SALES, SERVICE, WAREHOUSE; `job_title` required; `branch` in BANDUNG, BEKASI, CAKUNG, SUNTER, SURABAYA, TANGERANG; `hire_date` date; `employment_status` in ACTIVE, ON LEAVE, RESIGNED; `monthly_salary` money; `manager_id` optional identifier (D6) | `manager_id` to `employees` (nullable, self-reference) | `MANAGER_IS_SELF` |
| `suppliers` | `supplier_id` | `supplier_name` required; `contact_name`, `email`, `phone`, `city` optional; `payment_terms` (D2); `supplier_status` in ACTIVE, INACTIVE | none | none |
| `products` | `product_id` | `product_name` required; `product_category` in ASTRAMOBIL, AUTOPARTS, FLEETCARE, MOTOPRIMA, POWERGEN; `unit_of_measure` in LITER, PCS, SET, UNIT; `list_price`, `standard_cost` money; `is_active` flag (source column `active_flag`) | none | none |
| `sales_transactions` | `transaction_id` | `transaction_date` date; `customer_id`, `product_id`, `employee_id` optional identifiers; `branch` in the branch set; `quantity` integer at least 1; `unit_price` money; `discount_pct` percent; `payment_method` in CASH, CREDIT CARD, LEASING, TRANSFER; `transaction_status` in CANCELLED, COMPLETED, PENDING | `customer_id`, `product_id`, `employee_id` (all nullable) | none |
| `service_orders` | `service_order_id` | `service_date` date; `customer_id`, `product_id`, `technician_employee_id` optional; `branch`; `service_type` in INSPECTION, INSTALLATION, PERIODIC MAINTENANCE, REPAIR; `labor_amount`, `parts_amount` money; `service_status` in CANCELLED, COMPLETED, OPEN | `customer_id`, `product_id`, `technician_employee_id` (nullable) | none |
| `procurement` | `procurement_id` | `po_date`, `expected_delivery_date` date; `supplier_id`, `product_id`, `buyer_employee_id` optional; `quantity_ordered` integer at least 1; `unit_cost` money; `po_status` in CANCELLED, OPEN, PARTIAL, RECEIVED | `supplier_id`, `product_id`, `buyer_employee_id` (nullable) | none |
| `inventory` | `inventory_id` | `snapshot_date` date; `product_id` required identifier; `warehouse_code` required, upper-cased; `quantity_on_hand`, `reorder_point` integer at least 0; `unit_cost` money; `stock_status` in AVAILABLE, LOW STOCK, RESERVED | `product_id` (required) | `WAREHOUSE_CODE_FORMAT` |
| `expenses` | `expense_id` | `expense_date` date; `branch`; `department`; `submitted_by_employee_id` required identifier; `expense_category` in MAINTENANCE, MARKETING, OFFICE SUPPLIES, TRAINING, TRAVEL, UTILITIES; `amount` money (D4); `approval_status` in APPROVED, PENDING, REJECTED; `vendor_name` required | `submitted_by_employee_id` (required) | none |
| `attendance` | `attendance_id` | `attendance_date` date; `employee_id` required identifier; `branch`; `check_in`, `check_out` time (blank allowed); `attendance_status` in ABSENT, LATE, LEAVE, PRESENT | `employee_id` (required) | `CHECKOUT_BEFORE_CHECKIN` |

The source file must contain every source column, or the run stops with `missing columns`.
Extra columns in the file are ignored.

## Decisions D1-D6 as implemented

The questions and the owner's answers are in [HUMAN-STEPS.md](HUMAN-STEPS.md).

| ID | Decision | As implemented |
|---|---|---|
| D1 | Date `NN/NN/YYYY` is day-first, `NN-NN-YYYY` is month-first | `clean.date`. Also accepts `YYYY-MM-DD` and `YYYY/MM/DD`. Any other text or impossible date quarantines as `DATE_FORMAT_INVALID`. Times use `clean.time` and the same rule. Text dates such as `5 Jan 2025` are not accepted, so they quarantine |
| D2 | `NET30`, `NET 30`, `30 DAYS` mean Net 30 | `clean.payment_terms` maps all three to `NET30`. The original text is not kept in a separate audit column |
| D3 | Quantity of zero, negative or a word is quarantined | `integer(min_value=...)`: sales `quantity` and procurement `quantity_ordered` need at least 1; inventory `quantity_on_hand` and `reorder_point` need at least 0. Rule `NUMERIC_VALUE_INVALID`. No word-to-number guessing |
| D4 | Negative amounts are quarantined, not treated as refunds | `clean.money` raises for any negative money column. Rule `NEGATIVE_AMOUNT` |
| D5 | Exact duplicates: keep the first occurrence | The first copy is kept. Later exact copies are never loaded and are archived as `DUPLICATE_DROPPED` under rule `EXACT_DUPLICATE_ROW`. The HUMAN-STEPS text says they are logged as `DUPLICATE_PRIMARY_KEY`; the code uses `EXACT_DUPLICATE_ROW` for that case. `DUPLICATE_PRIMARY_KEY` is used only when the key repeats with different content |
| D6 | Blank `employees.manager_id` is allowed | `manager_id` is an optional identifier and a nullable foreign key. A manager that is quarantined puts their reports in quarantine as `ORPHAN_PARENT_QUARANTINED` |

## Limits to know

- The ETL checks the closed sets and formats above. It does not repeat every range check in the table definitions.
  For example `customers.registration_date >= 1990-01-01` is a database check, not a cleaner rule.
  A row that breaks only a database check fails the insert, and the whole load transaction rolls back (run status `FAILED`). Not implemented: a cleaner for those ranges.
- Strict quarantine decision (2026-11-17): rows that reference a quarantined parent are quarantined too, not loaded with a NULL key. See [doc 31](31-etl-and-quarantine.md).
- The run also writes counts per rule to `dataset.dq_check_result` (see [doc 07](07-etl-workflow.md)).
