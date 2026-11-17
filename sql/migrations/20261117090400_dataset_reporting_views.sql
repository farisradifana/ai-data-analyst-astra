-- 0005 — Reporting views for Looker Studio (no PII).
--
-- All views use security_invoker = true, so the caller's own grants and RLS policies apply
-- (no privilege escalation through the view owner). Looker Studio connects as astra_reporting
-- and should use these views, not the base tables that hold PII.

CREATE OR REPLACE VIEW dataset.v_customers_public WITH (security_invoker = true) AS
SELECT customer_id, customer_type, city, registration_date, customer_status
FROM dataset.customers;

CREATE OR REPLACE VIEW dataset.v_employees_public WITH (security_invoker = true) AS
SELECT employee_id, department, job_title, branch, hire_date, employment_status, manager_id
FROM dataset.employees;

CREATE OR REPLACE VIEW dataset.v_suppliers_public WITH (security_invoker = true) AS
SELECT supplier_id, supplier_name, city, payment_terms, supplier_status
FROM dataset.suppliers;

-- Daily sales by branch, product category and status.
CREATE OR REPLACE VIEW dataset.v_sales_daily WITH (security_invoker = true) AS
SELECT s.transaction_date                         AS sales_date,
       s.branch,
       coalesce(p.product_category, 'UNKNOWN')    AS product_category,
       s.payment_method,
       s.transaction_status,
       count(*)                                   AS transaction_count,
       sum(s.quantity)                            AS units,
       sum(s.gross_amount)                        AS gross_amount,
       sum(s.net_amount)                          AS net_amount,
       sum(s.gross_amount - s.net_amount)         AS discount_amount
FROM dataset.sales_transactions s
LEFT JOIN dataset.products p ON p.product_id = s.product_id
GROUP BY 1, 2, 3, 4, 5;

-- Daily after-sales service revenue.
CREATE OR REPLACE VIEW dataset.v_service_daily WITH (security_invoker = true) AS
SELECT service_date, branch, service_type, service_status,
       count(*)           AS order_count,
       sum(labor_amount)  AS labor_amount,
       sum(parts_amount)  AS parts_amount,
       sum(total_amount)  AS total_amount
FROM dataset.service_orders
GROUP BY 1, 2, 3, 4;

-- Monthly expenses by branch, department and category.
CREATE OR REPLACE VIEW dataset.v_expenses_monthly WITH (security_invoker = true) AS
SELECT date_trunc('month', expense_date)::date AS expense_month,
       branch, department, expense_category, approval_status,
       count(*)     AS expense_count,
       sum(amount)  AS amount
FROM dataset.expenses
GROUP BY 1, 2, 3, 4, 5;

-- Latest inventory snapshot per product and warehouse, with reorder flag.
CREATE OR REPLACE VIEW dataset.v_inventory_latest WITH (security_invoker = true) AS
SELECT DISTINCT ON (i.product_id, i.warehouse_code)
       i.product_id, p.product_category, i.warehouse_code, i.snapshot_date,
       i.quantity_on_hand, i.reorder_point, i.stock_status, i.stock_value,
       (i.quantity_on_hand <= i.reorder_point) AS below_reorder_point
FROM dataset.inventory i
JOIN dataset.products p ON p.product_id = i.product_id
ORDER BY i.product_id, i.warehouse_code, i.snapshot_date DESC, i.inventory_id DESC;

-- Pipeline health: per run and table, reconciliation counts.
CREATE OR REPLACE VIEW dataset.v_etl_run_summary WITH (security_invoker = true) AS
SELECT r.run_id, r.started_at, r.finished_at, r.status, r.trigger_type,
       f.table_name, f.rows_read, f.rows_loaded, f.rows_quarantined, f.rows_duplicate,
       round(100.0 * f.rows_loaded / nullif(f.rows_read, 0), 2) AS load_pct
FROM dataset.etl_run r
JOIN dataset.etl_run_file f ON f.run_id = r.run_id;

-- Open quarantine counts by table and issue (no record content).
CREATE OR REPLACE VIEW dataset.v_quarantine_open WITH (security_invoker = true) AS
SELECT table_name, issue_code, suggested_category,
       count(*)        AS open_records,
       min(created_at) AS oldest_created_at
FROM dataset.quarantine_record
WHERE status = 'OPEN'
GROUP BY 1, 2, 3;

DO $$
DECLARE
  v text;
  views text[] := ARRAY[
    'v_customers_public', 'v_employees_public', 'v_suppliers_public', 'v_sales_daily',
    'v_service_daily', 'v_expenses_monthly', 'v_inventory_latest', 'v_etl_run_summary',
    'v_quarantine_open'];
BEGIN
  FOREACH v IN ARRAY views LOOP
    EXECUTE format('REVOKE ALL ON dataset.%I FROM PUBLIC, anon, authenticated', v);
    EXECUTE format('GRANT SELECT ON dataset.%I TO astra_analyst, astra_reporting', v);
  END LOOP;
END
$$;
