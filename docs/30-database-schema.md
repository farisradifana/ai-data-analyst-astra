# 30 — Database Schema (Supabase, schema `dataset`)

Status 2026-11-17: all 5 migrations **applied** to the Supabase project through the connector
(migration names `astra_roles`, `dataset_schema_and_audit`, `dataset_core_tables`,
`dataset_rls_and_grants`, `dataset_reporting_views`). Before applying, the project was checked
read-only: no `dataset` schema, no `astra_*` roles, no tables in `public`.

Verified after apply: 14 tables, 9 views, 56 policies, RLS on every table, 0 rows, both roles
without password (cannot log in until the owner sets one).

## Migrations (`sql/migrations/`, apply in order)

| File | Creates |
|---|---|
| `20261117090000_astra_roles.sql` | Roles `astra_analyst` (ETL writer), `astra_reporting` (read-only); no password; session defaults (search_path, timeouts, reporting read-only). An existing role is never altered or dropped |
| `20261117090100_dataset_schema_and_audit.sql` | Schema `dataset` (no PUBLIC/anon/authenticated access); `etl_run`, `etl_run_file`, `dq_check_result`, `quarantine_record` |
| `20261117090200_dataset_core_tables.sql` | `customers`, `employees`, `suppliers`, `products`, `sales_transactions`, `service_orders`, `procurement`, `inventory`, `expenses`, `attendance` |
| `20261117090300_dataset_rls_and_grants.sql` | RLS on all 14 tables, per-role policies, table and column grants, default-privilege revokes |
| `20261117090400_dataset_reporting_views.sql` | 9 `security_invoker` views for Looker Studio |
| `20261117100000_quarantine_rule_catalog.sql` | `quarantine_rule` catalog (12 rules), `quarantine_record.rule_id` / `failed_columns` / `depends_on`, statuses OPEN / GRADUATED / SUPERSEDED / DISMISSED, views `v_quarantine_open` (+ rule columns) and `v_quarantine_lifecycle`. See doc 31 |
| `20261118090000_quarantine_correction.sql` | `quarantine_correction` (one fix per cell, applied by every ETL run; analyst SELECT/INSERT/UPDATE, no DELETE; reporting sees metadata only), `quarantine_record.corrected_columns`, view `v_correction_status`. See doc 31 |
| `20261118120000_live_quarantine.sql` | Each file read once (`source_file` registry; `etl_run_file` key now run + table + file). `quarantine_record` holds only rows still to fix (one per source row, `source_file`, `last_checked_run_id`); edits logged in `quarantine_edit`; rows that leave go to `quarantine_archive` (GRADUATED / DUPLICATE_DROPPED / DROPPED / SUPERSEDED, labels only). History of 0006/0007 moved to the archive; `quarantine_correction` now read-only legacy. Graduation path `FIX_SOURCE` renamed `FIX_IN_QUARANTINE`. `astra_analyst` gets DELETE on `quarantine_record` only. See doc 31 |

Every migration is idempotent (`IF NOT EXISTS`, `CREATE OR REPLACE`, `DROP POLICY IF EXISTS`).
None contains DROP TABLE, TRUNCATE or DELETE.

## Design rules

- Canonical values: trimmed UPPER CASE from closed sets taken from profiling (CHECK constraints).
  `payment_terms` keeps `COD` and `NET30` only (decision D2: `NET 30` / `30 DAYS` → `NET30`).
  `products.active_flag` becomes boolean `is_active`.
- Dates are `date`; money is `numeric(18,2)` IDR and never negative (D4 → quarantine).
- `sales_transactions.quantity > 0` (0, negative, `TWO` → quarantine, D3).
- Nullable foreign keys where the source may be blank; orphan keys are quarantined by the ETL.
  `employees.manager_id` self-FK is DEFERRABLE (D6 allows blank).
- Generated columns: `gross_amount`, `net_amount`, `total_amount`, `total_cost`, `stock_value`.
- Lineage on every business row: `etl_run_id`, `source_row_number`, `loaded_at`.
  `source_file` registers every file read; `etl_run_file` stores the source SHA-256 and the reconciliation `read = loaded + quarantined + duplicate`.

## Access model

| Role | Privileges |
|---|---|
| `astra_analyst` | USAGE on `dataset`; SELECT, INSERT, UPDATE on all tables. No DELETE, TRUNCATE or DDL |
| `astra_reporting` | SELECT on PII-free tables and all views; column-level SELECT on `customers`, `employees`, `suppliers`, `quarantine_record` without names, email, phone, salary, `raw_record`, `issue_detail`, `record_key`, `depends_on` (reporting may read `rule_id`, `failed_columns` and the `quarantine_rule` catalog) |
| `anon`, `authenticated`, PUBLIC | nothing |

RLS is enabled everywhere. Policies are `true` for the two app roles because the data is
synthetic and single-tenant; isolation is by role privilege. `dataset` must stay out of the
Data API "exposed schemas" list.

Looker Studio connects as `astra_reporting` and should use the `v_*` views. `SELECT *` on
`customers` / `employees` / `suppliers` is denied by design.

## Views

`v_customers_public`, `v_employees_public`, `v_suppliers_public`, `v_sales_daily`,
`v_service_daily`, `v_expenses_monthly`, `v_inventory_latest`, `v_etl_run_summary`,
`v_quarantine_open`, `v_quarantine_lifecycle` (open rows + archive), `v_correction_status` (legacy).

## Tests

`sql/tests/dataset_privilege_tests.sql` runs after the migrations, in one block that always
rolls back. It checks: analyst insert/update works and generated `net_amount` is right;
analyst DELETE and DDL are denied; `quantity = 0` is rejected; reporting reads views but not PII
or `raw_record` and cannot insert; anon and authenticated are denied; no table lacks RLS.

Result 2026-11-17 (all pass):
`analyst_insert=ok net=180000.00; analyst_update=ok; analyst_delete=denied; qty0=rejected;
analyst_ddl=denied; reporting_view_rows=1; reporting_customers_public=ok; reporting_pii=denied;
reporting_raw_record=denied; reporting_insert=denied; anon_select=denied; authenticated_view=denied;
tables_without_rls=0`. Afterwards 0 rows and no leftover role grants were confirmed.

## Supabase advisors (2026-11-17)

| Advisor | Finding | Handling |
|---|---|---|
| Security WARN | `public.rls_auto_enable()` is SECURITY DEFINER and executable by `anon` / `authenticated` via `/rest/v1/rpc/rls_auto_enable` | Not created by these migrations (existed before). Left unchanged pending owner decision |
| Performance INFO | 12 foreign keys without covering index (11 × `etl_run_id`, 1 × `employees.manager_id`) | Accepted: `etl_run` rows are never deleted or re-keyed. Revisit `manager_id` if org-chart queries are slow |
| Performance INFO | 20 unused indexes | Expected: tables are empty until the ETL runs |

## After applying (owner)

In the Supabase SQL editor (never in chat):
```sql
ALTER ROLE astra_analyst   PASSWORD '<long random>';
ALTER ROLE astra_reporting PASSWORD '<long random>';
```
Then fill the `.env` values from [HUMAN-STEPS.md](HUMAN-STEPS.md) H1.
