# 12 — Looker Studio

Last checked: 2026-11-18

Summary of the Looker Studio plan. The KPI catalogue, formulas, 2025 reference values and page layout are in
[doc 34](34-looker-studio-dashboards.md). All data is SYNTHETIC.

## Status

**The report is not built yet.** It is human step H5 in [HUMAN-STEPS.md](HUMAN-STEPS.md) (`H5 done` is unchecked).
The data side is ready: the views exist and were read as `astra_reporting` on 2026-11-18 ([doc 34](34-looker-studio-dashboards.md)).
Looker Studio runs in Google's cloud, so you build the report in the browser with your own Google account.

## Connection method

Looker Studio cannot reach a database on this PC. The decision (2026-11-17) is Supabase as managed Postgres.

| Setting | Value |
|---|---|
| Connector | PostgreSQL |
| Host and port | Supabase **Session pooler**, port 5432 (copy from the Supabase Connect page; this project uses the `aws-1` pooler) |
| Database | `postgres` |
| User | `astra_reporting.<project_ref>` (read-only role) |
| Password | The `astra_reporting` password. Enter it in Looker Studio only |
| SSL | Enable SSL and upload the Supabase CA certificate (`supabase-ca.crt`, kept in the untracked `secrets/` folder) |
| Schema | `dataset` |

- `astra_reporting` has no write privilege and cannot read names, emails, phones, salaries or record values ([doc 30](30-database-schema.md)).
- Never share the data source with "Anyone with the link can edit". Share the report as Viewer with named people only.

## Data sources

One data source per view in schema `dataset`. Use the `v_*` views, never the base tables.

| View | Used for |
|---|---|
| `v_sales_daily` | Sales KPIs |
| `v_customer_activity_monthly`, `v_customers_public` | Customers |
| `v_service_daily` | After-sales service |
| `v_procurement_monthly`, `v_inventory_latest` | Procurement and inventory |
| `v_expenses_monthly` | Expenses |
| `v_attendance_daily` | Attendance (no employee-level data) |
| `v_quarantine_monitor`, `v_quarantine_flow_daily`, `v_etl_run_summary` | Data quality |

Grain, date column and row counts of each view are in [doc 34](34-looker-studio-dashboards.md), "Data sources (views)".
Set date columns to type Date, money to Currency (IDR) and counts to Number.

## Planned pages

1. Executive overview
2. Sales
3. Customers
4. After-sales service
5. Procurement and inventory
6. Expenses
7. People (attendance)
8. Data quality (quarantine monitor)

Each page has a date range control and the filters listed in [doc 34](34-looker-studio-dashboards.md), "Report pages".

## KPI pointer

KPI ids (S1–S8, C1–C2, A1–A3, P1–P3, I1–I2, E1, H1–H4, Q1–Q3) are defined in [doc 34](34-looker-studio-dashboards.md), "KPI catalogue".
After building each scorecard, set the range to 2025 and compare it with the reference value. A different number means a filter or an aggregation is wrong.
The n8n data assistant uses the same definitions ([doc 13](13-n8n-ai-agent.md)).

## Freshness

Looker Studio caches data (default 12 h). After the daily load ([doc 33](33-daily-schedule.md)), use *Refresh data* or set the freshness to 1 hour.
