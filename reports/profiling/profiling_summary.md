# Raw Data Profiling Summary (Phase 1)

Generated: 2026-11-17T09:29:16+00:00  
Source: `raw-data/` (read-only). All data is SYNTHETIC.

## Source inventory

| Table | Rows | Cols | Size (KB) | Exact dup extra rows | PK dup keys | SHA-256 (first 12) |
|---|---:|---:|---:|---:|---:|---|
| attendance | 35,040 | 7 | 2,019 | 40 | 40 | `0032c096a587` |
| customers | 60,120 | 8 | 6,235 | 120 | 120 | `2b7f1495aa62` |
| employees | 5,025 | 10 | 613 | 25 | 25 | `c8399e08111e` |
| expenses | 25,025 | 9 | 2,491 | 25 | 25 | `bef4011f701e` |
| inventory | 35,080 | 8 | 2,577 | 80 | 80 | `f44a0d8526f6` |
| procurement | 30,045 | 9 | 2,552 | 45 | 45 | `c2c5718a71ed` |
| products | 5,035 | 7 | 389 | 35 | 35 | `41b21e81c642` |
| sales_transactions | 220,300 | 11 | 21,556 | 300 | 300 | `c717a783ef18` |
| service_orders | 18,020 | 10 | 1,936 | 20 | 20 | `d057c7d560fa` |
| suppliers | 1,510 | 8 | 165 | 10 | 10 | `9e022483de2b` |
| **TOTAL** | **435,200** | | **40,537** | **700** | **700** | |

## Referential integrity (orphan foreign keys)

| Child.column | Parent | Non-blank | Blank | Orphans | Examples |
|---|---|---:|---:|---:|---|
| attendance.employee_id | employees | 34,963 | 77 | 73 | EMP99999 |
| employees.manager_id | employees | 5,006 | 19 | 0 |  |
| expenses.submitted_by_employee_id | employees | 25,025 | 0 | 0 |  |
| inventory.product_id | products | 35,080 | 0 | 0 |  |
| procurement.supplier_id | suppliers | 30,022 | 23 | 66 | PRD99999, EMP99999, SUP9999 |
| procurement.product_id | products | 30,024 | 21 | 56 | EMP99999, PRD99999, SUP9999 |
| procurement.buyer_employee_id | employees | 30,030 | 15 | 70 | EMP99999, SUP9999, PRD99999 |
| sales_transactions.customer_id | customers | 220,221 | 79 | 245 | CUS999999, PRD99999, EMP99999 |
| sales_transactions.product_id | products | 220,219 | 81 | 245 | CUS999999, EMP99999, PRD99999 |
| sales_transactions.employee_id | employees | 220,211 | 89 | 261 | PRD99999, EMP99999, CUS999999 |
| service_orders.customer_id | customers | 18,004 | 16 | 42 | EMP99999, PRD99999, CUS999999 |
| service_orders.product_id | products | 18,008 | 12 | 46 | EMP99999, PRD99999, CUS999999 |
| service_orders.technician_employee_id | employees | 18,006 | 14 | 50 | EMP99999, CUS999999, PRD99999 |

## Column issues per table

### attendance

| Column | Kind | Missing % | Leading/trailing WS | Distinct raw / normalised | Notes |
|---|---|---:|---:|---|---|
| attendance_id | identifier | 0.0 | 0 | 35,000 / 35,000 |  |
| attendance_date | date | 0.0 | 0 | 2,676 / 2,676 | formats: YYYY-MM-DD=8756, YYYY/MM/DD=8672, DD/MM/YYYY=8734, MM-DD-YYYY=8878 |
| employee_id | identifier | 0.22 | 0 | 4,998 / 4,998 |  |
| branch | text | 0.0 | 6,986 | 24 / 6 | values: CAKUNG, BEKASI, SUNTER, BANDUNG, SURABAYA, TANGERANG |
| check_in | time | 20.057 | 0 | 5 / 5 |  |
| check_out | time | 19.957 | 0 | 5 / 5 |  |
| attendance_status | text | 0.0 | 6,880 | 16 / 4 | values: PRESENT, ABSENT, LATE, LEAVE |

### customers

| Column | Kind | Missing % | Leading/trailing WS | Distinct raw / normalised | Notes |
|---|---|---:|---:|---|---|
| customer_id | identifier | 0.0 | 0 | 60,000 / 60,000 |  |
| customer_name | text | 0.0 | 12,109 | 864 / 216 |  |
| customer_type | text | 0.0 | 12,028 | 8 / 2 | values: INDIVIDUAL, CORPORATE |
| email | email | 0.507 | 0 | 59,698 / 59,698 | invalid_format=220; sentinel=220 |
| phone | phone | 0.522 | 0 | 59,687 / 59,687 | sentinel=181; patterns: 99999999999, N/A, null |
| city | text | 0.467 | 11,965 | 43 / 13 | sentinel=189; values: BANDUNG, TANGERANG, JAKARTA, BOGOR, BEKASI, MAKASSAR, SURABAYA, SEMARANG, MEDAN, DEPOK, N/A, NULL |
| registration_date | date | 0.0 | 0 | 7,058 / 7,058 | formats: YYYY-MM-DD=14978, YYYY/MM/DD=14987, DD/MM/YYYY=15008, MM-DD-YYYY=15147 |
| customer_status | text | 0.0 | 12,194 | 8 / 2 | values: ACTIVE, INACTIVE |

### employees

| Column | Kind | Missing % | Leading/trailing WS | Distinct raw / normalised | Notes |
|---|---|---:|---:|---|---|
| employee_id | identifier | 0.0 | 0 | 5,000 / 5,000 |  |
| employee_name | text | 0.0 | 996 | 857 / 216 |  |
| email | email | 0.697 | 0 | 217 / 217 |  |
| department | text | 0.0 | 969 | 28 / 7 | values: SALES, HR, WAREHOUSE, AFTER SALES, SERVICE, FINANCE, PROCUREMENT |
| job_title | text | 0.0 | 1,032 | 33 / 8 | values: BRANCH MANAGER, BUYER, TECHNICIAN, WAREHOUSE OFFICER, ACCOUNTANT, HR OFFICER, SALES EXECUTIVE, SERVICE ADVISOR |
| branch | text | 0.0 | 1,049 | 24 / 6 | values: BANDUNG, TANGERANG, BEKASI, SUNTER, SURABAYA, CAKUNG |
| hire_date | date | 0.0 | 0 | 4,230 / 4,230 | formats: YYYY-MM-DD=1221, YYYY/MM/DD=1267, DD/MM/YYYY=1284, MM-DD-YYYY=1253 |
| employment_status | text | 0.0 | 1,016 | 12 / 3 | values: ACTIVE, RESIGNED, ON LEAVE |
| monthly_salary | money | 0.0 | 1,247 | 5,000 / 5,000 | with_rp_prefix=1,317; min=5,002,231 max=34,999,307 |
| manager_id | identifier | 0.378 | 0 | 301 / 301 |  |

### expenses

| Column | Kind | Missing % | Leading/trailing WS | Distinct raw / normalised | Notes |
|---|---|---:|---:|---|---|
| expense_id | identifier | 0.0 | 0 | 25,000 / 25,000 |  |
| expense_date | date | 0.0 | 0 | 5,534 / 5,534 | formats: YYYY-MM-DD=6159, YYYY/MM/DD=6312, DD/MM/YYYY=6194, MM-DD-YYYY=6360 |
| branch | text | 0.0 | 5,025 | 24 / 6 | values: CAKUNG, TANGERANG, BANDUNG, BEKASI, SUNTER, SURABAYA |
| department | text | 0.0 | 4,977 | 28 / 7 | values: HR, SALES, AFTER SALES, WAREHOUSE, FINANCE, PROCUREMENT, SERVICE |
| submitted_by_employee_id | identifier | 0.0 | 0 | 4,972 / 4,972 |  |
| expense_category | text | 0.0 | 5,088 | 24 / 6 | values: TRAVEL, TRAINING, UTILITIES, OFFICE SUPPLIES, MAINTENANCE, MARKETING |
| amount | money | 0.292 | 6,210 | 24,881 / 24,881 | with_rp_prefix=6,225; non_parsable=28; negative=47; sentinel=28; e.g. unknown; min=-50,000 max=49,999,571 |
| approval_status | text | 0.0 | 4,955 | 12 / 3 | values: APPROVED, PENDING, REJECTED |
| vendor_name | text | 0.0 | 4,945 | 360 / 72 |  |

### inventory

| Column | Kind | Missing % | Leading/trailing WS | Distinct raw / normalised | Notes |
|---|---|---:|---:|---|---|
| inventory_id | identifier | 0.0 | 0 | 35,000 / 35,000 |  |
| snapshot_date | date | 0.0 | 0 | 5,590 / 5,590 | formats: YYYY-MM-DD=8710, YYYY/MM/DD=8920, DD/MM/YYYY=8851, MM-DD-YYYY=8599 |
| product_id | identifier | 0.0 | 0 | 4,996 / 4,996 |  |
| warehouse_code | identifier | 0.0 | 7,044 | 16 / 4 | pattern_mismatch=13,956; e.g. Wh-Tgr-01, wh-tgr-01, wh-sun-01, Wh-Sun-01 |
| quantity_on_hand | numeric | 0.18 | 0 | 804 / 804 | non_parsable=28; negative=37; zero=49; sentinel=28; e.g. N/A; min=-5 max=800 |
| reorder_point | numeric | 0.0 | 0 | 141 / 141 | min=10 max=150 |
| unit_cost | money | 0.0 | 8,798 | 35,000 / 35,000 | with_rp_prefix=8,760; min=114,484 max=649,984,396 |
| stock_status | text | 0.0 | 7,021 | 12 / 3 | values: AVAILABLE, LOW STOCK, RESERVED |

### procurement

| Column | Kind | Missing % | Leading/trailing WS | Distinct raw / normalised | Notes |
|---|---|---:|---:|---|---|
| procurement_id | identifier | 0.0 | 0 | 30,000 / 30,000 |  |
| po_date | date | 0.0 | 0 | 5,568 / 5,568 | formats: YYYY-MM-DD=7569, YYYY/MM/DD=7504, DD/MM/YYYY=7265, MM-DD-YYYY=7707 |
| supplier_id | identifier | 0.077 | 0 | 1,504 / 1,504 |  |
| product_id | identifier | 0.07 | 0 | 4,990 / 4,990 |  |
| buyer_employee_id | identifier | 0.05 | 0 | 4,987 / 4,987 |  |
| quantity_ordered | numeric | 0.0 | 0 | 396 / 396 | min=5 max=400 |
| unit_cost | money | 0.0 | 7,380 | 30,000 / 30,000 | with_rp_prefix=7,461; min=102,407 max=599,992,259 |
| expected_delivery_date | date | 0.0 | 0 | 5,693 / 5,693 | formats: YYYY-MM-DD=7517, YYYY/MM/DD=7546, DD/MM/YYYY=7489, MM-DD-YYYY=7493 |
| po_status | text | 0.0 | 5,979 | 16 / 4 | values: RECEIVED, CANCELLED, PARTIAL, OPEN |

### products

| Column | Kind | Missing % | Leading/trailing WS | Distinct raw / normalised | Notes |
|---|---|---:|---:|---|---|
| product_id | identifier | 0.0 | 0 | 5,000 / 5,000 |  |
| product_name | text | 0.0 | 1,054 | 4,848 / 4,351 |  |
| product_category | text | 0.0 | 1,054 | 25 / 5 | values: POWERGEN, FLEETCARE, MOTOPRIMA, AUTOPARTS, ASTRAMOBIL |
| unit_of_measure | text | 0.0 | 1,013 | 16 / 4 | values: LITER, UNIT, SET, PCS |
| list_price | money | 0.0 | 1,236 | 4,932 / 4,932 | with_rp_prefix=1,242; non_parsable=39; negative=33; e.g. TBD; min=-1,000 max=849,737,577 |
| standard_cost | money | 0.0 | 1,242 | 5,000 / 5,000 | with_rp_prefix=1,305; min=157,271 max=649,896,316 |
| active_flag | text | 0.0 | 0 | 6 / 5 | values: Y, 1, 0, N, YES |

### sales_transactions

| Column | Kind | Missing % | Leading/trailing WS | Distinct raw / normalised | Notes |
|---|---|---:|---:|---|---|
| transaction_id | identifier | 0.0 | 0 | 220,000 / 220,000 |  |
| transaction_date | date | 0.0 | 0 | 5,600 / 5,600 | formats: YYYY-MM-DD=54799, YYYY/MM/DD=55162, DD/MM/YYYY=55093, MM-DD-YYYY=55246 |
| customer_id | identifier | 0.036 | 0 | 58,497 / 58,497 |  |
| product_id | identifier | 0.037 | 0 | 5,004 / 5,004 |  |
| employee_id | identifier | 0.04 | 0 | 5,004 / 5,004 |  |
| branch | text | 0.0 | 44,192 | 24 / 6 | values: BEKASI, SURABAYA, TANGERANG, CAKUNG, BANDUNG, SUNTER |
| quantity | numeric | 0.0 | 0 | 8 / 8 | non_parsable=99; negative=107; zero=94; e.g. two; min=-1 max=5 |
| unit_price | money | 0.0 | 55,303 | 219,999 / 219,997 | with_rp_prefix=55,147; min=261,743 max=849,995,364 |
| discount_pct | numeric | 0.0 | 73,431 | 12 / 8 | non_parsable=73,530; zero=73,356; e.g. 0%, 5%, 10%, 15%; min=0 max=15 |
| payment_method | text | 0.0 | 44,127 | 16 / 4 | values: LEASING, TRANSFER, CREDIT CARD, CASH |
| transaction_status | text | 0.0 | 43,908 | 12 / 3 | values: COMPLETED, CANCELLED, PENDING |

### service_orders

| Column | Kind | Missing % | Leading/trailing WS | Distinct raw / normalised | Notes |
|---|---|---:|---:|---|---|
| service_order_id | identifier | 0.0 | 0 | 18,000 / 18,000 |  |
| service_date | date | 0.0 | 0 | 5,376 / 5,376 | formats: YYYY-MM-DD=4458, YYYY/MM/DD=4469, DD/MM/YYYY=4572, MM-DD-YYYY=4521 |
| customer_id | identifier | 0.089 | 0 | 15,479 / 15,479 |  |
| product_id | identifier | 0.067 | 0 | 4,880 / 4,880 |  |
| technician_employee_id | identifier | 0.078 | 0 | 4,883 / 4,883 |  |
| branch | text | 0.0 | 3,610 | 24 / 6 | values: TANGERANG, BEKASI, SURABAYA, SUNTER, BANDUNG, CAKUNG |
| service_type | text | 0.0 | 3,535 | 16 / 4 | values: PERIODIC MAINTENANCE, INSPECTION, REPAIR, INSTALLATION |
| labor_amount | money | 0.0 | 4,507 | 17,995 / 17,993 | with_rp_prefix=4,461; min=100,663 max=7,999,765 |
| parts_amount | money | 0.0 | 4,533 | 17,999 / 17,998 | with_rp_prefix=4,456; min=1,495 max=29,999,060 |
| service_status | text | 0.0 | 3,540 | 12 / 3 | values: COMPLETED, OPEN, CANCELLED |

### suppliers

| Column | Kind | Missing % | Leading/trailing WS | Distinct raw / normalised | Notes |
|---|---|---:|---:|---|---|
| supplier_id | identifier | 0.0 | 0 | 1,500 / 1,500 |  |
| supplier_name | text | 0.0 | 293 | 797 / 216 |  |
| contact_name | text | 0.0 | 0 | 216 / 216 |  |
| email | email | 0.0 | 0 | 1,500 / 1,500 |  |
| phone | phone | 0.0 | 0 | 1,500 / 1,500 | patterns: 999-9999999 |
| city | text | 0.0 | 305 | 40 / 10 | values: SURABAYA, JAKARTA, MEDAN, TANGERANG, BANDUNG, DEPOK, MAKASSAR, BOGOR, SEMARANG, BEKASI |
| payment_terms | text | 0.0 | 286 | 16 / 4 | values: NET30, COD, 30 DAYS, NET 30 |
| supplier_status | text | 0.0 | 285 | 8 / 2 | values: ACTIVE, INACTIVE |
