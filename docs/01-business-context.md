# 01 — Business context

Last checked: 2026-11-18

This page describes the business that the synthetic data simulates.
It is based on the tables, views and KPI definitions in this repo.
It says nothing about the real Astra International. The data and the company model are invented (see [doc 00](00-project-overview.md)).

## The simulated business

A multi-branch vehicle and equipment group, in the style of an Astra International Sunter operation.
The data covers sales, after-sales service, procurement, inventory, HR attendance and operating expenses.

| Area | What the data holds | Table | Size at first load (source rows) |
|---|---|---|---:|
| Customers | Corporate and individual buyers, city, registration date, status | `customers` | 60,120 |
| Products | 5 categories, unit of measure, list price, standard cost, active flag | `products` | 5,035 |
| Sales | One row per transaction: quantity, unit price, discount, payment method, status | `sales_transactions` | 220,300 |
| After-sales service | Service orders by type with labor and parts amounts | `service_orders` | 18,020 |
| Procurement | Purchase orders to suppliers with expected delivery and status | `procurement` | 30,045 |
| Suppliers | Supplier master data with payment terms | `suppliers` | 1,510 |
| Inventory | Stock snapshots per product and warehouse, reorder point | `inventory` | 35,080 |
| HR | Employees (department, job title, branch, manager) | `employees` | 5,025 |
| Attendance | Daily check-in and check-out per employee | `attendance` | 35,040 |
| Expenses | Operating expenses by branch, department and category, with approval | `expenses` | 25,025 |

Source row counts include exact duplicates and rows that later go to quarantine. See [doc 04](04-source-inventory.md).

## Reference values

These are the closed sets that the database enforces (CHECK constraints in `sql/migrations/20261117090200_dataset_core_tables.sql`).

| Dimension | Values |
|---|---|
| Branches (6) | BANDUNG, BEKASI, CAKUNG, SUNTER, SURABAYA, TANGERANG |
| Departments (7) | AFTER SALES, FINANCE, HR, PROCUREMENT, SALES, SERVICE, WAREHOUSE |
| Product categories (5) | ASTRAMOBIL, AUTOPARTS, FLEETCARE, MOTOPRIMA, POWERGEN |
| Units of measure | LITER, PCS, SET, UNIT |
| Payment methods (sales) | CASH, CREDIT CARD, LEASING, TRANSFER |
| Sales status | CANCELLED, COMPLETED, PENDING |
| Service types | INSPECTION, INSTALLATION, PERIODIC MAINTENANCE, REPAIR |
| Service status | CANCELLED, COMPLETED, OPEN |
| PO status | CANCELLED, OPEN, PARTIAL, RECEIVED |
| Supplier payment terms | COD, NET30 |
| Stock status | AVAILABLE, LOW STOCK, RESERVED |
| Expense categories | MAINTENANCE, MARKETING, OFFICE SUPPLIES, TRAINING, TRAVEL, UTILITIES |
| Approval status | APPROVED, PENDING, REJECTED |
| Attendance status | ABSENT, LATE, LEAVE, PRESENT |

The profiling run also found these job titles in `employees`: BRANCH MANAGER, BUYER, TECHNICIAN, WAREHOUSE OFFICER,
ACCOUNTANT, HR OFFICER, SALES EXECUTIVE, SERVICE ADVISOR ([profiling summary](../reports/profiling/profiling_summary.md)).
The database does not restrict job titles to this list.

## Time span

Per [doc 34](34-looker-studio-dashboards.md): the data runs from 2023-01-01 to 2026-10-31.
Attendance starts on 2025-01-01. Customers are registered from 2022-01-01.

## Questions the platform answers

| Question | Where it is answered |
|---|---|
| How much did we sell, with what margin, and how many sales were cancelled? | Looker pages 1–2, assistant `get_sales_kpis`, `get_sales_breakdown`, `get_sales_monthly` |
| Which branch, product category or payment method drives revenue? | Same, by branch / category / payment method |
| How many customers buy each month, and how many are new? | Looker page 3, assistant `get_customer_activity` |
| How much service revenue do we earn, and how much of it is parts? | Looker page 4, assistant `get_service_kpis` |
| How much is on order, and which open purchase orders are overdue? | Looker page 5, assistant `get_procurement_inventory` |
| What is the stock worth, and which items are below the reorder point? | Looker page 5, assistant `get_procurement_inventory` |
| What do we spend on operations, by department and category? | Looker page 6, assistant `get_expense_summary` |
| How reliable is attendance (late, absent, hours worked)? | Looker page 7, assistant `get_attendance_kpis` |
| How clean is the incoming data, and what is waiting to be fixed? | Looker page 8, assistant `get_data_quality_status`, Telegram counts, `.\astra fix list` |

The assistant never returns personal data (names, emails, phones, salaries). The reporting role cannot read them ([doc 05](05-data-dictionary.md)).

## KPIs

The full catalogue (formula, source view, filter, 2025 reference value) is in [doc 34](34-looker-studio-dashboards.md).
Groups and ids:

| Group | Ids | Examples |
|---|---|---|
| Sales | S1–S8 | Net revenue, gross sales, discount rate, average order value, gross margin %, cancellation rate |
| Customers | C1–C2 | Buying customers per month, new customers |
| Service | A1–A3 | Service revenue, completed orders, parts share |
| Procurement | P1–P3 | Committed PO value, PO count, overdue open POs |
| Inventory | I1–I2 | Inventory value, items below reorder point |
| Expenses | E1 | Approved operating expenses |
| People | H1–H4 | Attendance, late and absence rates, average hours |
| Data quality | Q1–Q3 | Rows still to fix, rows graduated, load rate per run |

Business rules behind the numbers (all from doc 34):

- Revenue counts completed sales only. Service revenue counts completed service orders only.
- Ratios are recomputed from sums, never averaged.
- Sales without a product show as category `UNKNOWN`. Margin KPIs exclude them.
- Procurement amounts are far larger than sales because each table was generated independently.
  Do not read procurement against sales as a real ratio.

## Data quality as part of the business

The source files are deliberately messy: mixed date formats, money with `Rp` prefixes, case and spacing noise,
placeholder keys, duplicate rows. The ETL cleans what it can and holds the rest in quarantine until an analyst fixes it.
See [doc 31](31-etl-and-quarantine.md).
