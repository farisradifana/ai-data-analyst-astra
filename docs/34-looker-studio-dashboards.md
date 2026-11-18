# 34 — Looker Studio: KPIs and dashboard spec

This doc is the build sheet for the Looker Studio report (H5). All data is SYNTHETIC.
- Connection: see H5 in [HUMAN-STEPS.md](HUMAN-STEPS.md). Use Supabase Session pooler, SSL on with `supabase-ca.crt`, user `astra_reporting`.
- Views: migrations 0005, 0008 and 0010 (`sql/migrations/20261118170000_kpi_reporting_views.sql`).

## Rules

- **Use only the `v_*` views below, never the base tables.**
  - `astra_reporting` cannot read names, emails, phones, salaries or record values.
  - The views are already aggregated, so the report stays fast.
- **One data source per view, through CUSTOM QUERY.** The Looker Studio PostgreSQL table list shows only the
  `public` schema, and this project keeps everything in `dataset`, so the list after sign-in is empty. That is
  expected. In Looker Studio: Add data → PostgreSQL → enter the connection → choose **CUSTOM QUERY** (not TABLE)
  → query `SELECT * FROM dataset.v_sales_daily` (one view per data source) → Add. Do not put views in `public`.
  Then set the date column type to *Date*. Set money columns to *Currency (IDR)* and counts to *Number*.
- **Revenue counts only completed sales.** Filter `transaction_status = COMPLETED` (and `service_status = COMPLETED` for service).
- **Recompute ratios from sums.** Never average a ratio column. Example: `SUM(gross_margin) / SUM(net_amount)`.
- **Distinct counts stay at their view's grain.** Only use `v_customer_activity_monthly.buying_customers` per month and customer type.
  Never add it up across months: one customer buying in two months is counted in each month.
- **The `UNKNOWN` category means the row has no product**: the source left the product blank.
  Margin KPIs exclude it (12 completed sales in 2025).
- **Default date range:** "Last 12 months, up to 2026-10-31". The data runs from 2023-01-01 to 2026-10-31.
  Attendance starts on 2025-01-01. Customers registered from 2022-01-01.

## Data sources (views)

| View | Grain | Date column | Rows (2026-11-18) |
|---|---|---|---:|
| `v_sales_daily` | day × branch × product category × payment method × status | `sales_date` | 148,527 |
| `v_customer_activity_monthly` | month × customer type (completed sales) | `activity_month` | 92 |
| `v_customers_public` | customer (no PII) | `registration_date` | 60,000 |
| `v_service_daily` | day × branch × service type × status | `service_date` | 15,091 |
| `v_procurement_monthly` | month × product category × payment terms × PO status | `po_month` | 1,871 |
| `v_inventory_latest` | product × warehouse (`warehouse_code`), latest snapshot | `snapshot_date` | 16,269 |
| `v_expenses_monthly` | month × branch × department × `expense_category` × approval | `expense_month` | 14,366 |
| `v_attendance_daily` | day × branch × department × status | `attendance_date` | 25,655 |
| `v_quarantine_monitor` | table × rule × source file × failed columns × age bucket (rows still to fix) | `oldest_created_at` | 26 |
| `v_quarantine_flow_daily` | day × table × rule × event (ENTERED / GRADUATED / DUPLICATE_DROPPED / SUPERSEDED) | `event_date` | 57 |
| `v_quarantine_open`, `v_quarantine_lifecycle` | table × rule (× status) | — | 16 / 47 |
| `v_etl_run_summary` | run × table | `started_at` | 40 |

Every view was read as `astra_reporting` on 2026-11-18 (a full `count(*)`).
Most read in under 1 s. `v_sales_daily` took 1–4 s and `v_customer_activity_monthly` up to 1.6 s.
Keep the Looker data freshness at 1 hour or more so these are not re-read on every click.
The view totals match the base tables:
- completed net sales;
- procurement cost;
- attendance rows;
- quarantine rows: 5,914 open, and 26,666 entered = open + archive.

## KPI catalogue

The reference values are for calendar year 2025 (1 Jan – 31 Dec) unless the row says otherwise.
They were computed from the views on 2026-11-18. After building each scorecard, set the date range to 2025 and compare.
A different number means a filter or an aggregation is wrong.

| # | KPI | Looker formula (calculated field) | Source and filter | 2025 reference |
|---|---|---|---|---:|
| S1 | Net revenue | `SUM(net_amount)` | `v_sales_daily`, status COMPLETED | Rp 54,269,362,661,171 |
| S2 | Gross sales | `SUM(gross_amount)` | same | Rp 57,128,628,121,590 |
| S3 | Discount rate | `SUM(discount_amount) / SUM(gross_amount)` | same | 5.00 % |
| S4 | Completed transactions | `SUM(transaction_count)` | same | 44,689 |
| S5 | Average order value | `SUM(net_amount) / SUM(transaction_count)` | same | Rp 1,214,378,542 |
| S6 | Units sold | `SUM(units)` | same | 134,243 |
| S7 | Gross margin % | `SUM(gross_margin) / SUM(net_amount)` | same, and product category ≠ UNKNOWN | 18.53 % |
| S8 | Cancellation rate | `SUM(CASE WHEN transaction_status = "CANCELLED" THEN transaction_count ELSE 0 END) / SUM(transaction_count)` | `v_sales_daily`, all statuses | 9.99 % (5,588 / 55,922) |
| C1 | Buying customers per month | `SUM(buying_customers)` at one month × customer type, or summed over types for one month | `v_customer_activity_monthly` | Dec 2025: 3,624 |
| C2 | New customers | `COUNT(customer_id)` | `v_customers_public`, by `registration_date` | 12,314 |
| A1 | Service revenue | `SUM(total_amount)` | `v_service_daily`, status COMPLETED | Rp 69,266,735,528 |
| A2 | Completed service orders | `SUM(order_count)` | same | 3,618 |
| A3 | Parts share of service revenue | `SUM(parts_amount) / SUM(total_amount)` | same | 78.99 % |
| P1 | Committed PO value | `SUM(total_cost)` | `v_procurement_monthly`, status ≠ CANCELLED | Rp 413,023,573,348,402 |
| P2 | PO count | `SUM(po_count)` | same | 6,845 |
| P3 | Overdue open POs (now) | `SUM(overdue_po_count)` | `v_procurement_monthly`, no date filter | 6,449 (on 2026-11-18) |
| I1 | Inventory value (latest) | `SUM(stock_value)` | `v_inventory_latest`, no date filter | Rp 2,099,515,508,497,201 |
| I2 | Items below reorder point | `SUM(CASE WHEN below_reorder_point THEN 1 ELSE 0 END)` | same | 1,601 of 16,269 |
| E1 | Approved operating expenses | `SUM(amount)` | `v_expenses_monthly`, approval APPROVED | Rp 123,962,946,444 |
| H1 | Attendance rate | `SUM(CASE WHEN attendance_status IN ("PRESENT","LATE") THEN attendance_count ELSE 0 END) / SUM(attendance_count)` | `v_attendance_daily` | 82.04 % |
| H2 | Late rate (of those present) | LATE count / (PRESENT + LATE count) | same | 10.90 % |
| H3 | Absence rate | ABSENT count / all | same | 9.09 % |
| H4 | Average hours worked | `SUM(hours_worked) / SUM(timed_count)` | same | 8.98 h |
| Q1 | Rows still to fix | `SUM(open_records)` | `v_quarantine_monitor` | 5,914 (now) |
| Q2 | Rows graduated | `SUM(records)` where event = GRADUATED | `v_quarantine_flow_daily` | (by date) |
| Q3 | Load rate per run | `SUM(rows_loaded) / SUM(rows_read)` | `v_etl_run_summary` | (per run) |

Notes:
- The procurement amounts are much larger than sales. The data is synthetic and was generated independently per table.
  Do not read P1 against S1 as a real business ratio.
- P3 depends on today's date. It counts OPEN or PARTIAL POs whose expected delivery date is in the past.

## Report pages

On every page, put a date range control top right, plus the filter controls listed for that page.
Each control filters all charts on its page.

1. **Executive overview**
   - Scorecards S1, S7, S4, A1, E1, I1, each with a comparison to the previous period.
   - Time series: S1 by month.
   - Bar chart: S1 by branch.
   - Filters: branch, product category.
2. **Sales**
   - Scorecards S1–S8.
   - Time series: S1 and S5 by month.
   - Stacked bar: S1 by product category × branch.
   - Pie: payment method share of S4.
   - Table: branch × category with S1, S7, S3.
   - Filters: branch, product category, payment method, transaction status.
     The status filter defaults to COMPLETED; S8 ignores it.
3. **Customers**
   - Time series: C1 by month, broken down by customer type.
   - Time series: C2 by registration month.
   - Bar chart: customers by city (`v_customers_public`).
   - Filters: customer type, city, customer status.
4. **After-sales service**
   - Scorecards A1–A3.
   - Time series: A1 by month.
   - Bar chart: orders by service type × status.
   - Filters: branch, service type, service status.
5. **Procurement and inventory**
   - Scorecards P1–P3, I1, I2.
   - Time series: P1 by month and PO status.
   - Table: product category × `warehouse_code` with I1 and I2.
   - Filters: product category, payment terms, PO status, `warehouse_code`.
     Payment terms and PO status only filter procurement charts; `warehouse_code` only filters inventory.
6. **Expenses**
   - Scorecard E1.
   - Time series: E1 by month.
   - Treemap: E1 by department × `expense_category`.
   - Bar chart: E1 by branch.
   - Filters: branch, department, `expense_category`, approval status.
7. **People (attendance)**
   - Scorecards H1–H4.
   - Time series: H1 and H2 by month.
   - Heatmap table: branch × department with H1.
   - Filters: branch, department, attendance status.
   - No employee-level data: the view is grouped and has no IDs.
8. **Data quality (quarantine monitor)**: covers all tables.
   - Scorecard Q1, with a comparison to the previous period.
   - Bar charts: Q1 by `table_name`, and Q1 by `rule_id`.
   - Table: `v_quarantine_monitor` with table, rule, graduation path, failed columns, source file, age bucket,
     open and edited records, oldest date, last checked date.
   - Time series: `v_quarantine_flow_daily.records` by `event_date`, broken down by `event`.
     It shows what came in versus what graduated or was dropped as a duplicate.
     SUPERSEDED rows are history from before migration 0008.
   - Table: `v_etl_run_summary`, the latest runs, with Q3.
   - **Filters:** table name, rule, graduation path, source file, failed columns, age bucket, and event (on the flow chart).
   - Only tables that have rows still to fix appear in `v_quarantine_monitor`: 7 of 10 on 2026-11-18.
     A table missing from the chart has 0 rows in quarantine.
   - The page shows counts only. To see or fix a row, use `.\astra fix list` / `show` on the ETL machine.

## Sharing

- Share the report as "Viewer" with named people only.
- Keep the data source owner's credentials. Never use "Anyone with the link can edit".
- Looker Studio caches data (default 12 h). After a daily load, use *Refresh data* or set the freshness to 1 hour.
