-- 0010 — KPI views for Looker Studio (doc 34). No PII, no row-level keys of people.
--
-- Adds the inputs the KPI catalogue needs that 0005 lacked:
--   v_sales_daily            + cost_amount, gross_margin (appended columns; existing columns unchanged)
--   v_procurement_monthly    PO count, units, committed cost, overdue open POs
--   v_attendance_daily       attendance by branch / department / status, hours worked
--   v_customer_activity_monthly  distinct buying customers per month and customer type
--   v_quarantine_monitor     rows still to fix, all tables: rule, file, failed columns, age bucket
--   v_quarantine_flow_daily  rows entering / leaving quarantine per day and resolution
-- All views use security_invoker = true: astra_reporting's own column grants apply.
-- Every column used here is already granted to astra_reporting (checked 2026-11-18); no grant on a
-- base table changes.

-- cost_amount = quantity * products.standard_cost. Rows without a product (NULL product_id) have
-- cost NULL; sum() skips them, so gross_margin is only meaningful where product_category <> 'UNKNOWN'.
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
       sum(s.gross_amount - s.net_amount)         AS discount_amount,
       sum(s.quantity * p.standard_cost)          AS cost_amount,
       sum(s.net_amount - s.quantity * p.standard_cost) AS gross_margin
FROM dataset.sales_transactions s
LEFT JOIN dataset.products p ON p.product_id = s.product_id
GROUP BY 1, 2, 3, 4, 5;

-- overdue = still OPEN or PARTIAL and the expected delivery date is before the view is read.
CREATE OR REPLACE VIEW dataset.v_procurement_monthly WITH (security_invoker = true) AS
SELECT date_trunc('month', pr.po_date)::date        AS po_month,
       coalesce(p.product_category, 'UNKNOWN')      AS product_category,
       coalesce(sp.payment_terms, 'UNKNOWN')        AS payment_terms,
       pr.po_status,
       count(*)                                     AS po_count,
       sum(pr.quantity_ordered)                     AS units_ordered,
       sum(pr.total_cost)                           AS total_cost,
       count(*) FILTER (WHERE pr.po_status IN ('OPEN', 'PARTIAL')
                          AND pr.expected_delivery_date < current_date) AS overdue_po_count,
       sum(pr.total_cost) FILTER (WHERE pr.po_status IN ('OPEN', 'PARTIAL')
                          AND pr.expected_delivery_date < current_date) AS overdue_cost
FROM dataset.procurement pr
LEFT JOIN dataset.products  p  ON p.product_id = pr.product_id
LEFT JOIN dataset.suppliers sp ON sp.supplier_id = pr.supplier_id
GROUP BY 1, 2, 3, 4;

-- hours_worked counts only rows with both check_in and check_out.
CREATE OR REPLACE VIEW dataset.v_attendance_daily WITH (security_invoker = true) AS
SELECT a.attendance_date,
       a.branch,
       coalesce(e.department, 'UNKNOWN')            AS department,
       a.attendance_status,
       count(*)                                     AS attendance_count,
       count(*) FILTER (WHERE a.check_in IS NOT NULL AND a.check_out IS NOT NULL) AS timed_count,
       round(sum(extract(epoch FROM (a.check_out - a.check_in)) / 3600.0)
             FILTER (WHERE a.check_in IS NOT NULL AND a.check_out IS NOT NULL), 2) AS hours_worked
FROM dataset.attendance a
LEFT JOIN dataset.employees e ON e.employee_id = a.employee_id
GROUP BY 1, 2, 3, 4;

-- Distinct counts do not add up across rows: use this view at its own grain (month x customer type),
-- or sum transactions / net_amount only. Completed sales only; sales without a customer are excluded.
CREATE OR REPLACE VIEW dataset.v_customer_activity_monthly WITH (security_invoker = true) AS
SELECT date_trunc('month', s.transaction_date)::date AS activity_month,
       c.customer_type,
       count(DISTINCT s.customer_id)                AS buying_customers,
       count(*)                                     AS transactions,
       sum(s.net_amount)                            AS net_amount
FROM dataset.sales_transactions s
JOIN dataset.customers c ON c.customer_id = s.customer_id
WHERE s.transaction_status = 'COMPLETED'
GROUP BY 1, 2;

-- Quarantine monitor (all tables): rows still to fix, with the dimensions Looker filters on.
-- Column names only (failed_columns), never values; no record_key / depends_on (they hold keys).
CREATE OR REPLACE VIEW dataset.v_quarantine_monitor WITH (security_invoker = true) AS
SELECT q.table_name,
       q.rule_id,
       r.graduation_path,
       q.source_file,
       array_to_string(q.failed_columns, ', ')           AS failed_columns,
       CASE WHEN q.created_at >= now() - interval '7 days'  THEN '1: 0-7 days'
            WHEN q.created_at >= now() - interval '30 days' THEN '2: 8-30 days'
            WHEN q.created_at >= now() - interval '90 days' THEN '3: 31-90 days'
            ELSE '4: over 90 days' END                   AS age_bucket,
       count(*)                                          AS open_records,
       count(*) FILTER (WHERE cardinality(q.corrected_columns) > 0) AS edited_records,
       min(q.created_at)                                 AS oldest_created_at,
       max(q.last_checked_at)                            AS last_checked_at
FROM dataset.quarantine_record q
JOIN dataset.quarantine_rule r USING (rule_id)
GROUP BY 1, 2, 3, 4, 5, 6;

-- Quarantine flow per day (all tables): rows that entered quarantine, and rows that left it by resolution.
-- ENTERED counts every row ever quarantined (still open or archived). SUPERSEDED is history from before 0008.
CREATE OR REPLACE VIEW dataset.v_quarantine_flow_daily WITH (security_invoker = true) AS
SELECT event_date, table_name, rule_id, event, count(*) AS records
FROM (
  SELECT created_at::date AS event_date, table_name, rule_id, 'ENTERED' AS event FROM dataset.quarantine_record
  UNION ALL
  SELECT created_at::date, table_name, rule_id, 'ENTERED' FROM dataset.quarantine_archive
  UNION ALL
  SELECT resolved_at::date, table_name, rule_id, resolution FROM dataset.quarantine_archive
) e
GROUP BY 1, 2, 3, 4;

DO $$
DECLARE
  v text;
BEGIN
  FOREACH v IN ARRAY ARRAY['v_sales_daily', 'v_procurement_monthly', 'v_attendance_daily',
                           'v_customer_activity_monthly', 'v_quarantine_monitor', 'v_quarantine_flow_daily'] LOOP
    EXECUTE format('REVOKE ALL ON dataset.%I FROM PUBLIC, anon, authenticated', v);
    EXECUTE format('GRANT SELECT ON dataset.%I TO astra_analyst, astra_reporting', v);
  END LOOP;
END
$$;
