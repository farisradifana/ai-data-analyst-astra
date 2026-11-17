-- 0004 — Row Level Security and least-privilege grants for schema `dataset`.
--
-- Model (default deny):
--   * RLS enabled on every table. Roles without a policy see and change nothing.
--   * anon / authenticated / PUBLIC: no privileges, no policies.
--   * astra_analyst: SELECT, INSERT, UPDATE. No DELETE, no TRUNCATE, no DDL.
--   * astra_reporting: SELECT on non-PII columns only (column-level grants). PII columns
--     (names, email, phone, salary, quarantine raw_record) are not granted at all.
-- Data is synthetic and single-tenant, so row policies are `true` for the two app roles;
-- isolation comes from role privileges, not row filters.

GRANT USAGE ON SCHEMA dataset TO astra_analyst, astra_reporting;

DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'etl_run', 'etl_run_file', 'dq_check_result', 'quarantine_record',
    'customers', 'employees', 'suppliers', 'products',
    'sales_transactions', 'service_orders', 'procurement', 'inventory', 'expenses', 'attendance'];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    EXECUTE format('ALTER TABLE dataset.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('REVOKE ALL ON dataset.%I FROM PUBLIC, anon, authenticated', t);

    -- ETL writer
    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON dataset.%I TO astra_analyst', t);
    EXECUTE format('DROP POLICY IF EXISTS analyst_select ON dataset.%I', t);
    EXECUTE format('DROP POLICY IF EXISTS analyst_insert ON dataset.%I', t);
    EXECUTE format('DROP POLICY IF EXISTS analyst_update ON dataset.%I', t);
    EXECUTE format('CREATE POLICY analyst_select ON dataset.%I FOR SELECT TO astra_analyst USING (true)', t);
    EXECUTE format('CREATE POLICY analyst_insert ON dataset.%I FOR INSERT TO astra_analyst WITH CHECK (true)', t);
    EXECUTE format('CREATE POLICY analyst_update ON dataset.%I FOR UPDATE TO astra_analyst USING (true) WITH CHECK (true)', t);

    -- Read-only reporting (column privileges below decide which columns are visible)
    EXECUTE format('DROP POLICY IF EXISTS reporting_select ON dataset.%I', t);
    EXECUTE format('CREATE POLICY reporting_select ON dataset.%I FOR SELECT TO astra_reporting USING (true)', t);
  END LOOP;
END
$$;

GRANT USAGE ON ALL SEQUENCES IN SCHEMA dataset TO astra_analyst;

-- Reporting: full SELECT on tables without PII.
GRANT SELECT ON dataset.etl_run, dataset.etl_run_file, dataset.dq_check_result,
               dataset.products, dataset.sales_transactions, dataset.service_orders,
               dataset.procurement, dataset.inventory, dataset.expenses, dataset.attendance
  TO astra_reporting;

-- Reporting: column-level SELECT on tables that hold PII.
GRANT SELECT (customer_id, customer_type, city, registration_date, customer_status,
              etl_run_id, loaded_at)
  ON dataset.customers TO astra_reporting;

GRANT SELECT (employee_id, department, job_title, branch, hire_date, employment_status,
              manager_id, etl_run_id, loaded_at)
  ON dataset.employees TO astra_reporting;

GRANT SELECT (supplier_id, supplier_name, city, payment_terms, supplier_status,
              etl_run_id, loaded_at)
  ON dataset.suppliers TO astra_reporting;

GRANT SELECT (quarantine_id, run_id, table_name, source_row_number, issue_code, status,
              suggested_category, suggested_category_source, suggested_confidence,
              created_at, resolved_at, resolved_run_id)
  ON dataset.quarantine_record TO astra_reporting;

-- Future objects created by postgres in `dataset` never reach anon / authenticated.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA dataset
  REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA dataset
  REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA dataset
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;
