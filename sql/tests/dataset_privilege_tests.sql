-- Privilege and constraint tests for schema `dataset` (run AFTER migrations 0001-0005).
-- Everything runs in one DO block that always ends with RAISE EXCEPTION, so the whole
-- transaction (test rows and the temporary role grants) is rolled back. Nothing persists.
-- Expected: the error message lists every check; any "ALLOWED(BAD)" or tables_without_rls>0 is a failure.
DO $t$
DECLARE rid uuid; n numeric; res text := '';
BEGIN
  GRANT astra_analyst, astra_reporting TO postgres WITH SET TRUE, INHERIT FALSE;

  -- analyst: load path
  SET LOCAL ROLE astra_analyst;
  INSERT INTO dataset.etl_run (trigger_type) VALUES ('MANUAL') RETURNING run_id INTO rid;
  INSERT INTO dataset.products VALUES ('PRD00001','Test','AUTOPARTS','PCS',100000,80000,true,rid,1);
  INSERT INTO dataset.sales_transactions (transaction_id, transaction_date, product_id, branch, quantity,
     unit_price, discount_pct, payment_method, transaction_status, etl_run_id, source_row_number)
  VALUES ('TRX00001', DATE '2025-01-02', 'PRD00001', 'SUNTER', 2, 100000, 10, 'CASH', 'COMPLETED', rid, 2);
  SELECT net_amount INTO n FROM dataset.sales_transactions WHERE transaction_id = 'TRX00001';
  res := res || format(' analyst_insert=ok net=%s;', n);
  UPDATE dataset.etl_run SET status = 'SUCCEEDED', finished_at = now() WHERE run_id = rid;
  res := res || ' analyst_update=ok;';
  BEGIN
    DELETE FROM dataset.sales_transactions;
    res := res || ' analyst_delete=ALLOWED(BAD);';
  EXCEPTION WHEN insufficient_privilege THEN res := res || ' analyst_delete=denied;';
  END;
  BEGIN
    INSERT INTO dataset.sales_transactions (transaction_id, transaction_date, branch, quantity, unit_price,
       discount_pct, payment_method, transaction_status, etl_run_id, source_row_number)
    VALUES ('TRX00002', DATE '2025-01-02', 'SUNTER', 0, 1, 0, 'CASH', 'COMPLETED', rid, 3);
    res := res || ' qty0=ALLOWED(BAD);';
  EXCEPTION WHEN check_violation THEN res := res || ' qty0=rejected;';
  END;
  BEGIN
    EXECUTE 'CREATE TABLE dataset.x (i int)';
    res := res || ' analyst_ddl=ALLOWED(BAD);';
  EXCEPTION WHEN insufficient_privilege THEN res := res || ' analyst_ddl=denied;';
  END;
  RESET ROLE;

  -- reporting: read-only, no PII
  SET LOCAL ROLE astra_reporting;
  SELECT count(*) INTO n FROM dataset.v_sales_daily;
  res := res || format(' reporting_view_rows=%s;', n);
  SELECT count(*) INTO n FROM dataset.v_customers_public;
  res := res || ' reporting_customers_public=ok;';
  BEGIN
    PERFORM email FROM dataset.customers;
    res := res || ' reporting_pii=ALLOWED(BAD);';
  EXCEPTION WHEN insufficient_privilege THEN res := res || ' reporting_pii=denied;';
  END;
  BEGIN
    PERFORM raw_record FROM dataset.quarantine_record;
    res := res || ' reporting_raw_record=ALLOWED(BAD);';
  EXCEPTION WHEN insufficient_privilege THEN res := res || ' reporting_raw_record=denied;';
  END;
  BEGIN
    INSERT INTO dataset.etl_run DEFAULT VALUES;
    res := res || ' reporting_insert=ALLOWED(BAD);';
  EXCEPTION WHEN insufficient_privilege THEN res := res || ' reporting_insert=denied;';
  END;
  RESET ROLE;

  -- anon / authenticated: nothing
  BEGIN
    SET LOCAL ROLE anon;
    PERFORM 1 FROM dataset.products;
    res := res || ' anon_select=ALLOWED(BAD);';
  EXCEPTION WHEN insufficient_privilege THEN res := res || ' anon_select=denied;';
  END;
  RESET ROLE;
  BEGIN
    SET LOCAL ROLE authenticated;
    PERFORM 1 FROM dataset.v_sales_daily;
    res := res || ' authenticated_view=ALLOWED(BAD);';
  EXCEPTION WHEN insufficient_privilege THEN res := res || ' authenticated_view=denied;';
  END;
  RESET ROLE;

  SELECT count(*) INTO n FROM pg_tables WHERE schemaname = 'dataset' AND NOT rowsecurity;
  res := res || format(' tables_without_rls=%s;', n);
  RAISE EXCEPTION 'TEST_RESULT:%', res;
END
$t$;
