# 10 — SQL reference

Last checked: 2026-11-18

Every SQL file in the repository, and read-only example queries.
Objects and grants after all migrations are in [doc 09](09-postgresql-documentation.md). Schema design and test results are in [doc 30](30-database-schema.md).

## How the files are applied

- The migrations are plain SQL files in `sql/migrations/`, named `<yyyyMMddHHmmss>_<name>.sql`. Apply them in file name order.
- Doc 30 records that migrations 0001 to 0005 were applied to the Supabase project through the Supabase connector, after a read-only check of the project.
  [STATUS.md](STATUS.md) records that all 10 migrations are in place. The repository does not record how 0006 to 0010 were applied.
- There is no migration runner in the repository. Nothing in `src/` or `scripts/` applies a migration.
- The ETL connects as `astra_analyst`, which cannot run DDL. Migrations need an owner-level role, run by the project owner.
- Migrations 0001 to 0007 and 0010 can be re-run: they use `IF NOT EXISTS`, `CREATE OR REPLACE` and `DROP ... IF EXISTS`. Migration 0008 and 0009 are written to be re-run too, but 0008 was designed for a one-time move of history.
- No file sets or contains a password or a key.

## Migrations

Short names (0001 to 0010) are used in the docs. They are not part of the file names.

| No. | File | What it does | Objects | Destructive? |
|---|---|---|---|---|
| 0001 | `20261117090000_astra_roles.sql` | Creates the two login roles if missing and sets their session defaults (search path, timeouts, read-only for reporting). An existing role is only reported, never altered | Roles `astra_analyst`, `astra_reporting` | No. `ALTER ROLE ... SET` changes defaults on the roles, even when they already exist |
| 0002 | `20261117090100_dataset_schema_and_audit.sql` | Creates schema `dataset`, removes access for `PUBLIC`, `anon`, `authenticated`, and creates the audit tables | Schema `dataset`; tables `etl_run`, `etl_run_file`, `dq_check_result`, `quarantine_record` | No |
| 0003 | `20261117090200_dataset_core_tables.sql` | Creates the ten business tables with `CHECK` constraints, generated columns, foreign keys and indexes | `customers`, `employees`, `suppliers`, `products`, `sales_transactions`, `service_orders`, `procurement`, `inventory`, `expenses`, `attendance` | No |
| 0004 | `20261117090300_dataset_rls_and_grants.sql` | Enables RLS on the 14 tables, recreates the per-role policies, sets table and column grants, and revokes default privileges from `anon` and `authenticated` | Policies `analyst_select`, `analyst_insert`, `analyst_update`, `reporting_select`; grants | Revokes privileges and drops then recreates its own policies. No data is touched |
| 0005 | `20261117090400_dataset_reporting_views.sql` | Creates the nine reporting views with `security_invoker` and grants `SELECT` to both roles | `v_customers_public`, `v_employees_public`, `v_suppliers_public`, `v_sales_daily`, `v_service_daily`, `v_expenses_monthly`, `v_inventory_latest`, `v_etl_run_summary`, `v_quarantine_open` | No |
| 0006 | `20261117100000_quarantine_rule_catalog.sql` | Adds the rule catalog (12 rules), adds `rule_id`, `failed_columns`, `depends_on` to `quarantine_record`, changes the status check, replaces `v_quarantine_open`, adds `v_quarantine_lifecycle` | Table `quarantine_rule`; new columns; two views | Drops and recreates the status check constraint. The file says it was applied while `quarantine_record` was empty, which is why `rule_id` could be added as `NOT NULL`. On a table with rows that step would fail |
| 0007 | `20261118090000_quarantine_correction.sql` | Added the correction overlay (one fix per cell), the column `corrected_columns` and the view `v_correction_status` | Table `quarantine_correction` (dropped in 0009); column `quarantine_record.corrected_columns` (kept) | No |
| 0008 | `20261118120000_live_quarantine.sql` | Changes quarantine to a live table: adds `source_file`, `quarantine_archive`, `quarantine_edit`; copies the 0007 corrections to the edit log; moves non-open history to the archive; renames the graduation path `FIX_SOURCE` to `FIX_IN_QUARANTINE`; reseeds the rule catalog; replaces `v_quarantine_lifecycle`; grants `DELETE` on `quarantine_record` to `astra_analyst` | Tables `source_file`, `quarantine_archive`, `quarantine_edit`; new columns on `quarantine_record`; primary key of `etl_run_file` changed to `(run_id, table_name, file_name)` | Yes, limited. It runs `DELETE FROM dataset.quarantine_record WHERE status <> 'OPEN'` after copying those rows to the archive. It also drops and recreates constraints and revokes `INSERT`, `UPDATE` on the old correction table. The history is copied before the delete, in the same file |
| 0009 | `20261118150000_drop_legacy_correction.sql` | Drops the unused correction table and its view | Drops `quarantine_correction`, `v_correction_status`; comments on `quarantine_edit.legacy_correction_id` | Yes: `DROP TABLE`. A check at the start stops the script if any correction row was not copied to `quarantine_edit`. Approved 2026-11-18 per doc 30 |
| 0010 | `20261118170000_kpi_reporting_views.sql` | Replaces `v_sales_daily` (adds `cost_amount`, `gross_margin` at the end) and adds five KPI and quarantine views | `v_procurement_monthly`, `v_attendance_daily`, `v_customer_activity_monthly`, `v_quarantine_monitor`, `v_quarantine_flow_daily` | No. No base table grant changes |

Doc 30 says "None contains TRUNCATE or DELETE". That is out of date: 0008 contains one `DELETE` as described above. No migration contains `TRUNCATE`.

## Test file

| File | What it does | Destructive? |
|---|---|---|
| `sql/tests/dataset_privilege_tests.sql` | One `DO` block that runs as `astra_analyst`, `astra_reporting`, `anon` and `authenticated` and checks the privilege model. It ends with `RAISE EXCEPTION 'TEST_RESULT:...'`, so everything rolls back, including the test rows and the temporary role grants | No. It inserts and attempts forbidden statements, then rolls back |

The block checks 13 results: analyst insert, generated `net_amount`, analyst update, analyst `DELETE` denied, `quantity = 0` rejected, analyst DDL denied, reporting reads views, reporting cannot read a PII column or `raw_record`, reporting cannot insert, `anon` and `authenticated` denied, and the number of tables without RLS is 0.
The result is read from the error message. Any `ALLOWED(BAD)` is a failure.
Expected output and the 2026-11-17 result are in [doc 30](30-database-schema.md).
The header says to run it after migrations 0001 to 0005. It does not test the tables added later. Not implemented: privilege tests for `source_file`, `quarantine_archive`, `quarantine_edit` and `quarantine_rule`.

## Example queries

All examples read views only. Run them as `astra_reporting` (read only), for example in Navicat or the Supabase SQL editor.
Column names below were checked against the view definitions in migrations 0005, 0008 and 0010.
Do not add personal data to a query; the role cannot read it anyway.

Monthly completed net revenue for 2025 (`v_sales_daily`: `sales_date`, `branch`, `product_category`, `payment_method`, `transaction_status`, `transaction_count`, `units`, `gross_amount`, `net_amount`, `discount_amount`, `cost_amount`, `gross_margin`):

```sql
SELECT date_trunc('month', sales_date)::date AS sales_month,
       sum(net_amount)        AS net_revenue,
       sum(transaction_count) AS transactions
FROM dataset.v_sales_daily
WHERE transaction_status = 'COMPLETED'
  AND sales_date >= DATE '2025-01-01' AND sales_date < DATE '2026-01-01'
GROUP BY 1
ORDER BY 1;
```

Rows still to fix, by table and rule (`v_quarantine_monitor`: `table_name`, `rule_id`, `graduation_path`, `source_file`, `failed_columns`, `age_bucket`, `open_records`, `edited_records`, `oldest_created_at`, `last_checked_at`):

```sql
SELECT table_name, rule_id, graduation_path, sum(open_records) AS open_records
FROM dataset.v_quarantine_monitor
GROUP BY 1, 2, 3
ORDER BY 4 DESC;
```

Quarantine lifecycle totals (`v_quarantine_lifecycle`: `table_name`, `rule_id`, `graduation_path`, `status`, `records`, `last_change_at`; status is `OPEN` or an archive resolution):

```sql
SELECT table_name, status, sum(records) AS records
FROM dataset.v_quarantine_lifecycle
GROUP BY 1, 2
ORDER BY 1, 2;
```

Rows entering and leaving quarantine in the last 30 days (`v_quarantine_flow_daily`: `event_date`, `table_name`, `rule_id`, `event`, `records`):

```sql
SELECT event_date, event, sum(records) AS records
FROM dataset.v_quarantine_flow_daily
WHERE event_date >= current_date - 30
GROUP BY 1, 2
ORDER BY 1, 2;
```

Counts and duration of the latest ETL run (`v_etl_run_summary`: `run_id`, `started_at`, `finished_at`, `status`, `trigger_type`, `table_name`, `rows_read`, `rows_loaded`, `rows_quarantined`, `rows_duplicate`, `load_pct`):

```sql
SELECT table_name, status, trigger_type,
       finished_at - started_at AS duration,
       rows_read, rows_loaded, rows_quarantined, rows_duplicate, load_pct
FROM dataset.v_etl_run_summary
WHERE run_id = (SELECT run_id FROM dataset.etl_run ORDER BY started_at DESC LIMIT 1)
ORDER BY table_name;
```

Products at or below the reorder point (`v_inventory_latest`: `product_id`, `product_category`, `warehouse_code`, `snapshot_date`, `quantity_on_hand`, `reorder_point`, `stock_status`, `stock_value`, `below_reorder_point`):

```sql
SELECT product_category,
       count(*) FILTER (WHERE below_reorder_point) AS items_below_reorder,
       count(*)                                    AS items
FROM dataset.v_inventory_latest
GROUP BY 1
ORDER BY 1;
```

Overdue purchase orders by month (`v_procurement_monthly`: `po_month`, `product_category`, `payment_terms`, `po_status`, `po_count`, `units_ordered`, `total_cost`, `overdue_po_count`, `overdue_cost`):

```sql
SELECT po_month,
       sum(po_count)         AS po_count,
       sum(overdue_po_count) AS overdue_po_count,
       sum(overdue_cost)     AS overdue_cost
FROM dataset.v_procurement_monthly
WHERE po_month >= DATE '2026-01-01'
GROUP BY 1
ORDER BY 1;
```

Other views and their columns: `v_attendance_daily` (`attendance_date`, `branch`, `department`, `attendance_status`, `attendance_count`, `timed_count`, `hours_worked`), `v_customer_activity_monthly` (`activity_month`, `customer_type`, `buying_customers`, `transactions`, `net_amount`), `v_service_daily` (`service_date`, `branch`, `service_type`, `service_status`, `order_count`, `labor_amount`, `parts_amount`, `total_amount`), `v_expenses_monthly` (`expense_month`, `branch`, `department`, `expense_category`, `approval_status`, `expense_count`, `amount`), `v_quarantine_open` (`table_name`, `issue_code`, `suggested_category`, `open_records`, `oldest_created_at`, `rule_id`, `graduation_path`, `remediation`).
KPI formulas and the dashboards that use these views: [doc 34](34-looker-studio-dashboards.md).
