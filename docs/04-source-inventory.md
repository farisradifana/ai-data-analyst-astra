# 04 — Source inventory

Last checked: 2026-11-18

Ten CSV files make up the source. All data is synthetic. The files are not in Git (`raw-data/` is ignored).
Numbers come from `reports/profiling/source_inventory.csv` and [profiling_summary.md](../reports/profiling/profiling_summary.md),
produced by `scripts/profile_raw.py` on 2026-11-17.

## Files

All files are UTF-8 with BOM (`utf-8-sig`) and comma-delimited. Rows exclude the header line.

| Table | File | Rows | Columns | Bytes | Primary key | Exact duplicate extra rows |
|---|---|---:|---:|---:|---|---:|
| attendance | `attendance.csv` | 35,040 | 7 | 2,068,099 | `attendance_id` | 40 |
| customers | `customers.csv` | 60,120 | 8 | 6,385,052 | `customer_id` | 120 |
| employees | `employees.csv` | 5,025 | 10 | 628,588 | `employee_id` | 25 |
| expenses | `expenses.csv` | 25,025 | 9 | 2,550,840 | `expense_id` | 25 |
| inventory | `inventory.csv` | 35,080 | 8 | 2,639,276 | `inventory_id` | 80 |
| procurement | `procurement.csv` | 30,045 | 9 | 2,613,829 | `procurement_id` | 45 |
| products | `products.csv` | 5,035 | 7 | 398,554 | `product_id` | 35 |
| sales_transactions | `sales_transactions.csv` | 220,300 | 11 | 22,073,493 | `transaction_id` | 300 |
| service_orders | `service_orders.csv` | 18,020 | 10 | 1,983,271 | `service_order_id` | 20 |
| suppliers | `suppliers.csv` | 1,510 | 8 | 169,524 | `supplier_id` | 10 |
| **Total** | | **435,200** | | **41,510,526** (40,537 KB) | | **700** |

Every duplicate primary key is an exact full-row duplicate (`pk_duplicate_keys` equals the duplicate extra rows in every table).

## Headers

Only the header line of each file is listed here.

| Table | Columns, in file order |
|---|---|
| attendance | `attendance_id, attendance_date, employee_id, branch, check_in, check_out, attendance_status` |
| customers | `customer_id, customer_name, customer_type, email, phone, city, registration_date, customer_status` |
| employees | `employee_id, employee_name, email, department, job_title, branch, hire_date, employment_status, monthly_salary, manager_id` |
| expenses | `expense_id, expense_date, branch, department, submitted_by_employee_id, expense_category, amount, approval_status, vendor_name` |
| inventory | `inventory_id, snapshot_date, product_id, warehouse_code, quantity_on_hand, reorder_point, unit_cost, stock_status` |
| procurement | `procurement_id, po_date, supplier_id, product_id, buyer_employee_id, quantity_ordered, unit_cost, expected_delivery_date, po_status` |
| products | `product_id, product_name, product_category, unit_of_measure, list_price, standard_cost, active_flag` |
| sales_transactions | `transaction_id, transaction_date, customer_id, product_id, employee_id, branch, quantity, unit_price, discount_pct, payment_method, transaction_status` |
| service_orders | `service_order_id, service_date, customer_id, product_id, technician_employee_id, branch, service_type, labor_amount, parts_amount, service_status` |
| suppliers | `supplier_id, supplier_name, contact_name, email, phone, city, payment_terms, supplier_status` |

The ETL stops with `missing columns` if a file lacks a column it maps (`read_source` in `src/astra_etl/transform.py`).
Only one column is renamed on load: `products.active_flag` becomes `is_active`.

## Checksum policy

- The ETL computes the SHA-256 of every source file. The profiling run also recorded them in `source_inventory.csv`.
- A file that was read is registered in `dataset.source_file` with its SHA-256, and in `dataset.etl_run_file` per run.
- A registered file is never read again.
- If a registered file has a different checksum, the run stops with an error. Restore the file and send new data as a new file.
- A new file with the same content as a loaded file is skipped.
- After profiling, the raw checksums were verified unchanged (10 of 10), per [STATUS](STATUS.md).

## File layout the ETL reads

As implemented in `discover()` in `src/astra_etl/transform.py`, for each table the ETL reads, in this order:

1. `raw-data/<table>.csv` (the first delivery).
2. `raw-data/<table>/*.csv`, in file name order (later deliveries).

Example: `raw-data/sales_transactions/2026-11-19.csv`. A date in the name keeps the files in order.
No other name pattern is matched. A file such as `raw-data/<table>_20261119.csv` placed directly in `raw-data/` is not read.
The `_20261119` and `_20261120` files now in `raw-data/` are kept there on purpose and are not loads
(decision 2026-11-18). To load a daily file, move it into `raw-data/<table>/`.
(On 2026-11-18, `raw-data/` held 30 top-level files, 3 per table, including names of that form, and no sub-folders.
Their contents were not inspected for this page.)

Details of a run and of the quarantine lifecycle: [doc 31](31-etl-and-quarantine.md).

## Known data issues (from profiling)

- Dates mix four formats (about 25% each): `YYYY-MM-DD`, `YYYY/MM/DD`, `DD/MM/YYYY`, `MM-DD-YYYY`.
  Rule: slash with year last is day first, dash with year last is month first (decision D1).
- Money mixes `Rp 1,353,708`, `1,353,708.00` and plain numbers. Invalid tokens exist (`unknown`, `TBD`) and some amounts are negative.
- Categories have case and whitespace noise (for example 24 raw branch values reduce to 6).
- Some foreign keys hold placeholder or wrong-entity ids (for example `EMP99999`).
- Phone numbers have leading zeros, so they are text.

How each issue is handled: [doc 05](05-data-dictionary.md) (per column) and [doc 31](31-etl-and-quarantine.md).
