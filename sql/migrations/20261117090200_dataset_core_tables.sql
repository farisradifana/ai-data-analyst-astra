-- 0003 — Clean business tables in schema `dataset` (SYNTHETIC data).
--
-- Values are stored in canonical form produced by the ETL:
--   * codes / statuses: trimmed UPPER CASE from the closed sets below (profiled 2026-11-17)
--   * dates: ISO `date` (mixed raw formats resolved by decision D1)
--   * money: numeric(18,2) in IDR, never negative (negatives quarantined, decision D4)
-- Rows that fail a constraint are never loaded; the ETL writes them to dataset.quarantine_record.
-- Foreign keys that may be blank in the source are nullable; orphan keys are quarantined.
-- Every table carries lineage: etl_run_id, source_row_number, loaded_at.

-- ---------------------------------------------------------------- dimensions

CREATE TABLE IF NOT EXISTS dataset.customers (
  customer_id        text PRIMARY KEY CHECK (customer_id ~ '^[A-Z0-9-]{1,32}$'),
  customer_name      text NOT NULL CHECK (char_length(customer_name) BETWEEN 1 AND 200),  -- PII
  customer_type      text NOT NULL CHECK (customer_type IN ('CORPORATE', 'INDIVIDUAL')),
  email              text CHECK (char_length(email) <= 254),                               -- PII
  phone              text CHECK (char_length(phone) <= 32),                                -- PII
  city               text CHECK (char_length(city) <= 100),
  registration_date  date NOT NULL CHECK (registration_date >= DATE '1990-01-01'),
  customer_status    text NOT NULL CHECK (customer_status IN ('ACTIVE', 'INACTIVE')),
  etl_run_id         uuid NOT NULL REFERENCES dataset.etl_run (run_id),
  source_row_number  integer NOT NULL CHECK (source_row_number >= 1),
  loaded_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dataset.employees (
  employee_id        text PRIMARY KEY CHECK (employee_id ~ '^[A-Z0-9-]{1,32}$'),
  employee_name      text NOT NULL CHECK (char_length(employee_name) BETWEEN 1 AND 200),  -- PII
  email              text CHECK (char_length(email) <= 254),                               -- PII
  department         text NOT NULL CHECK (department IN
                       ('AFTER SALES', 'FINANCE', 'HR', 'PROCUREMENT', 'SALES', 'SERVICE', 'WAREHOUSE')),
  job_title          text NOT NULL CHECK (char_length(job_title) BETWEEN 1 AND 100),
  branch             text NOT NULL CHECK (branch IN
                       ('BANDUNG', 'BEKASI', 'CAKUNG', 'SUNTER', 'SURABAYA', 'TANGERANG')),
  hire_date          date NOT NULL CHECK (hire_date >= DATE '1970-01-01'),
  employment_status  text NOT NULL CHECK (employment_status IN ('ACTIVE', 'ON LEAVE', 'RESIGNED')),
  monthly_salary     numeric(18,2) NOT NULL CHECK (monthly_salary >= 0),                   -- sensitive
  manager_id         text,  -- blank allowed (decision D6)
  etl_run_id         uuid NOT NULL REFERENCES dataset.etl_run (run_id),
  source_row_number  integer NOT NULL CHECK (source_row_number >= 1),
  loaded_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT employees_manager_fk FOREIGN KEY (manager_id)
    REFERENCES dataset.employees (employee_id) DEFERRABLE INITIALLY DEFERRED,
  CHECK (manager_id IS NULL OR manager_id <> employee_id)
);

CREATE TABLE IF NOT EXISTS dataset.suppliers (
  supplier_id        text PRIMARY KEY CHECK (supplier_id ~ '^[A-Z0-9-]{1,32}$'),
  supplier_name      text NOT NULL CHECK (char_length(supplier_name) BETWEEN 1 AND 200),
  contact_name       text CHECK (char_length(contact_name) <= 200),                        -- PII
  email              text CHECK (char_length(email) <= 254),                               -- PII
  phone              text CHECK (char_length(phone) <= 32),                                -- PII
  city               text CHECK (char_length(city) <= 100),
  payment_terms      text NOT NULL CHECK (payment_terms IN ('COD', 'NET30')),  -- decision D2
  supplier_status    text NOT NULL CHECK (supplier_status IN ('ACTIVE', 'INACTIVE')),
  etl_run_id         uuid NOT NULL REFERENCES dataset.etl_run (run_id),
  source_row_number  integer NOT NULL CHECK (source_row_number >= 1),
  loaded_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dataset.products (
  product_id         text PRIMARY KEY CHECK (product_id ~ '^[A-Z0-9-]{1,32}$'),
  product_name       text NOT NULL CHECK (char_length(product_name) BETWEEN 1 AND 200),
  product_category   text NOT NULL CHECK (product_category IN
                       ('ASTRAMOBIL', 'AUTOPARTS', 'FLEETCARE', 'MOTOPRIMA', 'POWERGEN')),
  unit_of_measure    text NOT NULL CHECK (unit_of_measure IN ('LITER', 'PCS', 'SET', 'UNIT')),
  list_price         numeric(18,2) NOT NULL CHECK (list_price >= 0),
  standard_cost      numeric(18,2) NOT NULL CHECK (standard_cost >= 0),
  is_active          boolean NOT NULL,  -- raw active_flag 1/Y/YES -> true, 0/N -> false
  etl_run_id         uuid NOT NULL REFERENCES dataset.etl_run (run_id),
  source_row_number  integer NOT NULL CHECK (source_row_number >= 1),
  loaded_at          timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- facts

CREATE TABLE IF NOT EXISTS dataset.sales_transactions (
  transaction_id     text PRIMARY KEY CHECK (transaction_id ~ '^[A-Z0-9-]{1,32}$'),
  transaction_date   date NOT NULL CHECK (transaction_date >= DATE '2000-01-01'),
  customer_id        text REFERENCES dataset.customers (customer_id),
  product_id         text REFERENCES dataset.products (product_id),
  employee_id        text REFERENCES dataset.employees (employee_id),
  branch             text NOT NULL CHECK (branch IN
                       ('BANDUNG', 'BEKASI', 'CAKUNG', 'SUNTER', 'SURABAYA', 'TANGERANG')),
  quantity           integer NOT NULL CHECK (quantity > 0),  -- 0, negative, text -> quarantine (D3)
  unit_price         numeric(18,2) NOT NULL CHECK (unit_price >= 0),
  discount_pct       numeric(5,2) NOT NULL CHECK (discount_pct BETWEEN 0 AND 100),
  payment_method     text NOT NULL CHECK (payment_method IN ('CASH', 'CREDIT CARD', 'LEASING', 'TRANSFER')),
  transaction_status text NOT NULL CHECK (transaction_status IN ('CANCELLED', 'COMPLETED', 'PENDING')),
  gross_amount       numeric(20,2) GENERATED ALWAYS AS (round(quantity * unit_price, 2)) STORED,
  net_amount         numeric(20,2) GENERATED ALWAYS AS
                       (round(quantity * unit_price * (1 - discount_pct / 100), 2)) STORED,
  etl_run_id         uuid NOT NULL REFERENCES dataset.etl_run (run_id),
  source_row_number  integer NOT NULL CHECK (source_row_number >= 1),
  loaded_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sales_transactions_date_idx     ON dataset.sales_transactions (transaction_date);
CREATE INDEX IF NOT EXISTS sales_transactions_customer_idx ON dataset.sales_transactions (customer_id);
CREATE INDEX IF NOT EXISTS sales_transactions_product_idx  ON dataset.sales_transactions (product_id);
CREATE INDEX IF NOT EXISTS sales_transactions_employee_idx ON dataset.sales_transactions (employee_id);

CREATE TABLE IF NOT EXISTS dataset.service_orders (
  service_order_id   text PRIMARY KEY CHECK (service_order_id ~ '^[A-Z0-9-]{1,32}$'),
  service_date       date NOT NULL CHECK (service_date >= DATE '2000-01-01'),
  customer_id        text REFERENCES dataset.customers (customer_id),
  product_id         text REFERENCES dataset.products (product_id),
  technician_employee_id text REFERENCES dataset.employees (employee_id),
  branch             text NOT NULL CHECK (branch IN
                       ('BANDUNG', 'BEKASI', 'CAKUNG', 'SUNTER', 'SURABAYA', 'TANGERANG')),
  service_type       text NOT NULL CHECK (service_type IN
                       ('INSPECTION', 'INSTALLATION', 'PERIODIC MAINTENANCE', 'REPAIR')),
  labor_amount       numeric(18,2) NOT NULL CHECK (labor_amount >= 0),
  parts_amount       numeric(18,2) NOT NULL CHECK (parts_amount >= 0),
  service_status     text NOT NULL CHECK (service_status IN ('CANCELLED', 'COMPLETED', 'OPEN')),
  total_amount       numeric(20,2) GENERATED ALWAYS AS (labor_amount + parts_amount) STORED,
  etl_run_id         uuid NOT NULL REFERENCES dataset.etl_run (run_id),
  source_row_number  integer NOT NULL CHECK (source_row_number >= 1),
  loaded_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS service_orders_date_idx       ON dataset.service_orders (service_date);
CREATE INDEX IF NOT EXISTS service_orders_customer_idx   ON dataset.service_orders (customer_id);
CREATE INDEX IF NOT EXISTS service_orders_product_idx    ON dataset.service_orders (product_id);
CREATE INDEX IF NOT EXISTS service_orders_technician_idx ON dataset.service_orders (technician_employee_id);

CREATE TABLE IF NOT EXISTS dataset.procurement (
  procurement_id     text PRIMARY KEY CHECK (procurement_id ~ '^[A-Z0-9-]{1,32}$'),
  po_date            date NOT NULL CHECK (po_date >= DATE '2000-01-01'),
  supplier_id        text REFERENCES dataset.suppliers (supplier_id),
  product_id         text REFERENCES dataset.products (product_id),
  buyer_employee_id  text REFERENCES dataset.employees (employee_id),
  quantity_ordered   integer NOT NULL CHECK (quantity_ordered > 0),
  unit_cost          numeric(18,2) NOT NULL CHECK (unit_cost >= 0),
  expected_delivery_date date NOT NULL,
  po_status          text NOT NULL CHECK (po_status IN ('CANCELLED', 'OPEN', 'PARTIAL', 'RECEIVED')),
  total_cost         numeric(20,2) GENERATED ALWAYS AS (quantity_ordered * unit_cost) STORED,
  etl_run_id         uuid NOT NULL REFERENCES dataset.etl_run (run_id),
  source_row_number  integer NOT NULL CHECK (source_row_number >= 1),
  loaded_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS procurement_date_idx     ON dataset.procurement (po_date);
CREATE INDEX IF NOT EXISTS procurement_supplier_idx ON dataset.procurement (supplier_id);
CREATE INDEX IF NOT EXISTS procurement_product_idx  ON dataset.procurement (product_id);
CREATE INDEX IF NOT EXISTS procurement_buyer_idx    ON dataset.procurement (buyer_employee_id);

CREATE TABLE IF NOT EXISTS dataset.inventory (
  inventory_id       text PRIMARY KEY CHECK (inventory_id ~ '^[A-Z0-9-]{1,32}$'),
  snapshot_date      date NOT NULL CHECK (snapshot_date >= DATE '2000-01-01'),
  product_id         text NOT NULL REFERENCES dataset.products (product_id),
  warehouse_code     text NOT NULL CHECK (warehouse_code ~ '^WH-[A-Z]{3}-[0-9]{2}$'),
  quantity_on_hand   integer NOT NULL CHECK (quantity_on_hand >= 0),
  reorder_point      integer NOT NULL CHECK (reorder_point >= 0),
  unit_cost          numeric(18,2) NOT NULL CHECK (unit_cost >= 0),
  stock_status       text NOT NULL CHECK (stock_status IN ('AVAILABLE', 'LOW STOCK', 'RESERVED')),
  stock_value        numeric(20,2) GENERATED ALWAYS AS (quantity_on_hand * unit_cost) STORED,
  etl_run_id         uuid NOT NULL REFERENCES dataset.etl_run (run_id),
  source_row_number  integer NOT NULL CHECK (source_row_number >= 1),
  loaded_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS inventory_date_idx    ON dataset.inventory (snapshot_date);
CREATE INDEX IF NOT EXISTS inventory_product_idx ON dataset.inventory (product_id);

CREATE TABLE IF NOT EXISTS dataset.expenses (
  expense_id         text PRIMARY KEY CHECK (expense_id ~ '^[A-Z0-9-]{1,32}$'),
  expense_date       date NOT NULL CHECK (expense_date >= DATE '2000-01-01'),
  branch             text NOT NULL CHECK (branch IN
                       ('BANDUNG', 'BEKASI', 'CAKUNG', 'SUNTER', 'SURABAYA', 'TANGERANG')),
  department         text NOT NULL CHECK (department IN
                       ('AFTER SALES', 'FINANCE', 'HR', 'PROCUREMENT', 'SALES', 'SERVICE', 'WAREHOUSE')),
  submitted_by_employee_id text NOT NULL REFERENCES dataset.employees (employee_id),
  expense_category   text NOT NULL CHECK (expense_category IN
                       ('MAINTENANCE', 'MARKETING', 'OFFICE SUPPLIES', 'TRAINING', 'TRAVEL', 'UTILITIES')),
  amount             numeric(18,2) NOT NULL CHECK (amount >= 0),  -- negatives quarantined (D4)
  approval_status    text NOT NULL CHECK (approval_status IN ('APPROVED', 'PENDING', 'REJECTED')),
  vendor_name        text NOT NULL CHECK (char_length(vendor_name) BETWEEN 1 AND 200),
  etl_run_id         uuid NOT NULL REFERENCES dataset.etl_run (run_id),
  source_row_number  integer NOT NULL CHECK (source_row_number >= 1),
  loaded_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS expenses_date_idx      ON dataset.expenses (expense_date);
CREATE INDEX IF NOT EXISTS expenses_submitter_idx ON dataset.expenses (submitted_by_employee_id);

CREATE TABLE IF NOT EXISTS dataset.attendance (
  attendance_id      text PRIMARY KEY CHECK (attendance_id ~ '^[A-Z0-9-]{1,32}$'),
  attendance_date    date NOT NULL CHECK (attendance_date >= DATE '2000-01-01'),
  employee_id        text NOT NULL REFERENCES dataset.employees (employee_id),
  branch             text NOT NULL CHECK (branch IN
                       ('BANDUNG', 'BEKASI', 'CAKUNG', 'SUNTER', 'SURABAYA', 'TANGERANG')),
  check_in           time,  -- blank for ABSENT / LEAVE
  check_out          time,
  attendance_status  text NOT NULL CHECK (attendance_status IN ('ABSENT', 'LATE', 'LEAVE', 'PRESENT')),
  etl_run_id         uuid NOT NULL REFERENCES dataset.etl_run (run_id),
  source_row_number  integer NOT NULL CHECK (source_row_number >= 1),
  loaded_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (check_in IS NULL OR check_out IS NULL OR check_out >= check_in)
);
CREATE INDEX IF NOT EXISTS attendance_date_idx     ON dataset.attendance (attendance_date);
CREATE INDEX IF NOT EXISTS attendance_employee_idx ON dataset.attendance (employee_id);
