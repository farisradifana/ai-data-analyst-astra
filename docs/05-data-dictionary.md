# 05 — Data dictionary

Last checked: 2026-11-18

Columns of the 10 core tables in schema `dataset`. All data is synthetic.
Types and nullability come from `sql/migrations/20261117090200_dataset_core_tables.sql`.
Source columns and cleaning rules come from `src/astra_etl/spec.py` and `src/astra_etl/clean.py`.
Meanings are taken from the column names and constraints. Grants come from `20261117090300_dataset_rls_and_grants.sql`.

## Reading the tables

- **Source column** is the CSV header. It equals the target name unless shown otherwise.
- **Null** is `N` for NOT NULL and `Y` for nullable.
- **PII** marks personal or sensitive data. A column marked **Denied** cannot be read by `astra_reporting`
  (so not by Looker Studio or the n8n assistant). `astra_analyst` can read all columns.
- A row that fails any cleaning rule is not loaded. It goes to quarantine with an issue code (see [doc 31](31-etl-and-quarantine.md)).

## Cleaning rules

| Rule | What it does | Failure code |
|---|---|---|
| ID | Trim, upper case, must match `[A-Z0-9-]{1,32}`. Blank or placeholder (`N/A`, `NA`, `NULL`, `NONE`, `-`, `UNKNOWN`, `TBD`, empty) fails, or becomes NULL where the column is nullable | `MISSING_REQUIRED_FIELD`, `INVALID_CATEGORY` |
| CODE | Trim, collapse spaces, upper case, must be in the closed set listed for the column | `MISSING_REQUIRED_FIELD`, `INVALID_CATEGORY` |
| NAME | Trim, collapse spaces, Title Case | `MISSING_REQUIRED_FIELD` |
| DATE | Accepts `YYYY-MM-DD`, `YYYY/MM/DD`, `DD/MM/YYYY`, `MM-DD-YYYY` (decision D1); invalid calendar dates fail | `MISSING_REQUIRED_FIELD`, `INVALID_DATE_FORMAT` |
| TIME | Accepts `08:00`, `08.15`, `8:30 AM`, `5:00 PM`. Blank becomes NULL | `INVALID_DATE_FORMAT` |
| MONEY | Removes `Rp` prefix, commas and spaces, rounds to 2 decimals. Negative fails (decision D4) | `INVALID_NUMERIC_VALUE`, `BUSINESS_RULE_VIOLATION` |
| INT>=n | Whole number at least n. Words such as `two` are not guessed (decision D3) | `INVALID_NUMERIC_VALUE` |
| PERCENT | `10` or `10%`, must be 0 to 100, 2 decimals | `INVALID_NUMERIC_VALUE` |
| FLAG | `Y`, `YES`, `1`, `TRUE` give true. `N`, `NO`, `0`, `FALSE` give false | `MISSING_REQUIRED_FIELD`, `INVALID_CATEGORY` |
| EMAIL | Lower case. Blank, placeholder or invalid format becomes NULL | none (optional) |
| PHONE | Kept as written. Placeholder, all-9 digits or bad format becomes NULL | none (optional) |
| CITY | Trim, upper case. Placeholder becomes NULL | none (optional) |

## Lineage columns (every core table)

| Column | Type | Null | Meaning |
|---|---|---|---|
| `etl_run_id` | uuid | N | The ETL run that loaded the row. Foreign key to `etl_run (run_id)` |
| `source_row_number` | integer, at least 1 | N | Line number in the source file (the header is line 1) |
| `loaded_at` | timestamptz, default `now()` | N | When the row was loaded |

`source_row_number` is denied to `astra_reporting` on `customers`, `employees` and `suppliers`. It is readable on the other tables.

## customers

| Column | Type | Null | Meaning | Source | Rule | PII / reporting |
|---|---|---|---|---|---|---|
| `customer_id` | text, PK | N | Customer key | same | ID | Readable |
| `customer_name` | text, 1–200 chars | N | Customer or company name | same | NAME | PII. Denied |
| `customer_type` | text | N | CORPORATE or INDIVIDUAL | same | CODE | Readable |
| `email` | text, max 254 | Y | Contact email | same | EMAIL | PII. Denied |
| `phone` | text, max 32 | Y | Contact phone (text, keeps leading zeros) | same | PHONE | PII. Denied |
| `city` | text, max 100 | Y | Customer city | same | CITY | Readable |
| `registration_date` | date, at least 1990-01-01 | N | Date the customer registered | same | DATE | Readable |
| `customer_status` | text | N | ACTIVE or INACTIVE | same | CODE | Readable |

## employees

| Column | Type | Null | Meaning | Source | Rule | PII / reporting |
|---|---|---|---|---|---|---|
| `employee_id` | text, PK | N | Employee key | same | ID | Readable |
| `employee_name` | text, 1–200 chars | N | Employee name | same | NAME | PII. Denied |
| `email` | text, max 254 | Y | Work email | same | EMAIL | PII. Denied |
| `department` | text | N | AFTER SALES, FINANCE, HR, PROCUREMENT, SALES, SERVICE, WAREHOUSE | same | CODE | Readable |
| `job_title` | text, 1–100 chars | N | Job title | same | Trim, upper case, required | Readable |
| `branch` | text | N | BANDUNG, BEKASI, CAKUNG, SUNTER, SURABAYA, TANGERANG | same | CODE | Readable |
| `hire_date` | date, at least 1970-01-01 | N | Hire date | same | DATE | Readable |
| `employment_status` | text | N | ACTIVE, ON LEAVE or RESIGNED | same | CODE | Readable |
| `monthly_salary` | numeric(18,2), at least 0 | N | Monthly salary in IDR | same | MONEY | Sensitive. Denied |
| `manager_id` | text, FK to `employees` | Y | Manager. Blank allowed (decision D6). Deferrable foreign key | same | ID, nullable. Rule `MANAGER_IS_SELF` rejects `manager_id = employee_id` | Readable |

## suppliers

| Column | Type | Null | Meaning | Source | Rule | PII / reporting |
|---|---|---|---|---|---|---|
| `supplier_id` | text, PK | N | Supplier key | same | ID | Readable |
| `supplier_name` | text, 1–200 chars | N | Supplier company name | same | NAME | Readable |
| `contact_name` | text, max 200 | Y | Contact person | same | NAME, nullable | PII. Denied |
| `email` | text, max 254 | Y | Contact email | same | EMAIL | PII. Denied |
| `phone` | text, max 32 | Y | Contact phone | same | PHONE | PII. Denied |
| `city` | text, max 100 | Y | Supplier city | same | CITY | Readable |
| `payment_terms` | text | N | COD or NET30. `NET 30` and `30 DAYS` map to NET30 (decision D2) | same | Mapping from D2 | Readable |
| `supplier_status` | text | N | ACTIVE or INACTIVE | same | CODE | Readable |

## products

| Column | Type | Null | Meaning | Source | Rule | PII / reporting |
|---|---|---|---|---|---|---|
| `product_id` | text, PK | N | Product key | same | ID | Readable |
| `product_name` | text, 1–200 chars | N | Product name | same | NAME | Readable |
| `product_category` | text | N | ASTRAMOBIL, AUTOPARTS, FLEETCARE, MOTOPRIMA, POWERGEN | same | CODE | Readable |
| `unit_of_measure` | text | N | LITER, PCS, SET or UNIT | same | CODE | Readable |
| `list_price` | numeric(18,2), at least 0 | N | List price in IDR. `TBD` or negative stays in quarantine | same | MONEY | Readable |
| `standard_cost` | numeric(18,2), at least 0 | N | Standard cost in IDR | same | MONEY | Readable |
| `is_active` | boolean | N | Product is active | `active_flag` | FLAG | Readable |

## sales_transactions

| Column | Type | Null | Meaning | Source | Rule | PII / reporting |
|---|---|---|---|---|---|---|
| `transaction_id` | text, PK | N | Transaction key | same | ID | Readable |
| `transaction_date` | date, at least 2000-01-01 | N | Sale date | same | DATE | Readable |
| `customer_id` | text, FK `customers` | Y | Buyer | same | ID, nullable | Readable |
| `product_id` | text, FK `products` | Y | Product sold. Blank shows as category `UNKNOWN` in views | same | ID, nullable | Readable |
| `employee_id` | text, FK `employees` | Y | Salesperson | same | ID, nullable | Readable |
| `branch` | text | N | Branch (six values, see `employees.branch`) | same | CODE | Readable |
| `quantity` | integer, above 0 | N | Units sold. 0, negative or text goes to quarantine (D3) | same | INT>=1 | Readable |
| `unit_price` | numeric(18,2), at least 0 | N | Price per unit in IDR | same | MONEY | Readable |
| `discount_pct` | numeric(5,2), 0 to 100 | N | Discount in percent | same | PERCENT | Readable |
| `payment_method` | text | N | CASH, CREDIT CARD, LEASING or TRANSFER | same | CODE | Readable |
| `transaction_status` | text | N | CANCELLED, COMPLETED or PENDING | same | CODE | Readable |
| `gross_amount` | numeric(20,2), generated | Y | `round(quantity * unit_price, 2)` | computed | Generated by the database | Readable |
| `net_amount` | numeric(20,2), generated | Y | `round(quantity * unit_price * (1 - discount_pct / 100), 2)` | computed | Generated by the database | Readable |

## service_orders

| Column | Type | Null | Meaning | Source | Rule | PII / reporting |
|---|---|---|---|---|---|---|
| `service_order_id` | text, PK | N | Service order key | same | ID | Readable |
| `service_date` | date, at least 2000-01-01 | N | Service date | same | DATE | Readable |
| `customer_id` | text, FK `customers` | Y | Customer | same | ID, nullable | Readable |
| `product_id` | text, FK `products` | Y | Product serviced | same | ID, nullable | Readable |
| `technician_employee_id` | text, FK `employees` | Y | Technician | same | ID, nullable | Readable |
| `branch` | text | N | Branch | same | CODE | Readable |
| `service_type` | text | N | INSPECTION, INSTALLATION, PERIODIC MAINTENANCE or REPAIR | same | CODE | Readable |
| `labor_amount` | numeric(18,2), at least 0 | N | Labor charge in IDR | same | MONEY | Readable |
| `parts_amount` | numeric(18,2), at least 0 | N | Parts charge in IDR | same | MONEY | Readable |
| `service_status` | text | N | CANCELLED, COMPLETED or OPEN | same | CODE | Readable |
| `total_amount` | numeric(20,2), generated | Y | `labor_amount + parts_amount` | computed | Generated by the database | Readable |

## procurement

| Column | Type | Null | Meaning | Source | Rule | PII / reporting |
|---|---|---|---|---|---|---|
| `procurement_id` | text, PK | N | Purchase order key | same | ID | Readable |
| `po_date` | date, at least 2000-01-01 | N | Purchase order date | same | DATE | Readable |
| `supplier_id` | text, FK `suppliers` | Y | Supplier | same | ID, nullable | Readable |
| `product_id` | text, FK `products` | Y | Product ordered | same | ID, nullable | Readable |
| `buyer_employee_id` | text, FK `employees` | Y | Buyer | same | ID, nullable | Readable |
| `quantity_ordered` | integer, above 0 | N | Units ordered | same | INT>=1 | Readable |
| `unit_cost` | numeric(18,2), at least 0 | N | Cost per unit in IDR | same | MONEY | Readable |
| `expected_delivery_date` | date | N | Expected delivery | same | DATE | Readable |
| `po_status` | text | N | CANCELLED, OPEN, PARTIAL or RECEIVED | same | CODE | Readable |
| `total_cost` | numeric(20,2), generated | Y | `quantity_ordered * unit_cost` | computed | Generated by the database | Readable |

## inventory

| Column | Type | Null | Meaning | Source | Rule | PII / reporting |
|---|---|---|---|---|---|---|
| `inventory_id` | text, PK | N | Snapshot row key | same | ID | Readable |
| `snapshot_date` | date, at least 2000-01-01 | N | Date of the stock snapshot | same | DATE | Readable |
| `product_id` | text, FK `products` | N | Product | same | ID | Readable |
| `warehouse_code` | text | N | Warehouse, format `WH-AAA-00` | same | Trim, upper case, required. Rule `WAREHOUSE_CODE_FORMAT` | Readable |
| `quantity_on_hand` | integer, at least 0 | N | Units in stock. `N/A` or negative goes to quarantine | same | INT>=0 | Readable |
| `reorder_point` | integer, at least 0 | N | Stock level that triggers reorder | same | INT>=0 | Readable |
| `unit_cost` | numeric(18,2), at least 0 | N | Cost per unit in IDR | same | MONEY | Readable |
| `stock_status` | text | N | AVAILABLE, LOW STOCK or RESERVED | same | CODE | Readable |
| `stock_value` | numeric(20,2), generated | Y | `quantity_on_hand * unit_cost` | computed | Generated by the database | Readable |

## expenses

| Column | Type | Null | Meaning | Source | Rule | PII / reporting |
|---|---|---|---|---|---|---|
| `expense_id` | text, PK | N | Expense key | same | ID | Readable |
| `expense_date` | date, at least 2000-01-01 | N | Expense date | same | DATE | Readable |
| `branch` | text | N | Branch | same | CODE | Readable |
| `department` | text | N | Department (seven values, see `employees.department`) | same | CODE | Readable |
| `submitted_by_employee_id` | text, FK `employees` | N | Employee who submitted the expense | same | ID | Readable |
| `expense_category` | text | N | MAINTENANCE, MARKETING, OFFICE SUPPLIES, TRAINING, TRAVEL or UTILITIES | same | CODE | Readable |
| `amount` | numeric(18,2), at least 0 | N | Expense amount in IDR. `unknown` or negative goes to quarantine (D4) | same | MONEY | Readable |
| `approval_status` | text | N | APPROVED, PENDING or REJECTED | same | CODE | Readable |
| `vendor_name` | text, 1–200 chars | N | Vendor | same | NAME | Readable |

## attendance

| Column | Type | Null | Meaning | Source | Rule | PII / reporting |
|---|---|---|---|---|---|---|
| `attendance_id` | text, PK | N | Attendance key | same | ID | Readable |
| `attendance_date` | date, at least 2000-01-01 | N | Day | same | DATE | Readable |
| `employee_id` | text, FK `employees` | N | Employee | same | ID | Readable |
| `branch` | text | N | Branch | same | CODE | Readable |
| `check_in` | time | Y | Check-in time. Blank for ABSENT or LEAVE | same | TIME | Readable |
| `check_out` | time | Y | Check-out time | same | TIME. Rule `CHECKOUT_BEFORE_CHECKIN` rejects a check-out before the check-in | Readable |
| `attendance_status` | text | N | ABSENT, LATE, LEAVE or PRESENT | same | CODE | Readable |

## PII summary

| Table | Denied to `astra_reporting` |
|---|---|
| `customers` | `customer_name`, `email`, `phone`, `source_row_number` |
| `employees` | `employee_name`, `email`, `monthly_salary`, `source_row_number` |
| `suppliers` | `contact_name`, `email`, `phone`, `source_row_number` |
| `quarantine_record` | `raw_record`, `issue_detail`, `record_key`, `depends_on` (the source row may hold PII) |

Looker Studio and the assistant use the `v_*` views, which contain none of these columns.
`SELECT *` on `customers`, `employees` and `suppliers` is denied to the reporting role by design.
The grant model is in [doc 30](30-database-schema.md). The table relationships are in [doc 03](03-data-architecture.md).
