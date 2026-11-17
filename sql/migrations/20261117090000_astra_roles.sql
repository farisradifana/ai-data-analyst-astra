-- 0001 — Application roles for the Astra analytics platform (SYNTHETIC data).
--
-- astra_analyst   : ETL writer (insert/update in schema dataset, no DELETE/TRUNCATE/DDL).
-- astra_reporting : read-only reader for Looker Studio, n8n and Navicat (no PII columns).
--
-- Passwords are NOT set here. The owner sets them in the Supabase SQL editor:
--   ALTER ROLE astra_analyst   PASSWORD '<long random>';
--   ALTER ROLE astra_reporting PASSWORD '<long random>';
-- Until then neither role can log in.
--
-- Safe to re-run: an existing role is left untouched (only reported), never altered or dropped.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'astra_analyst') THEN
    CREATE ROLE astra_analyst LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
      NOINHERIT CONNECTION LIMIT 5;
  ELSE
    RAISE NOTICE 'role astra_analyst already exists; not modified';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'astra_reporting') THEN
    CREATE ROLE astra_reporting LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
      NOINHERIT CONNECTION LIMIT 10;
  ELSE
    RAISE NOTICE 'role astra_reporting already exists; not modified';
  END IF;
END
$$;

-- Session defaults (apply to new sessions of each role).
ALTER ROLE astra_analyst   SET search_path = dataset;
ALTER ROLE astra_analyst   SET statement_timeout = '15min';
ALTER ROLE astra_analyst   SET idle_in_transaction_session_timeout = '5min';

ALTER ROLE astra_reporting SET search_path = dataset;
ALTER ROLE astra_reporting SET default_transaction_read_only = on;
ALTER ROLE astra_reporting SET statement_timeout = '60s';
ALTER ROLE astra_reporting SET idle_in_transaction_session_timeout = '60s';

COMMENT ON ROLE astra_analyst   IS 'Astra ETL writer: INSERT/UPDATE on schema dataset only';
COMMENT ON ROLE astra_reporting IS 'Astra read-only reporting (Looker Studio, n8n, Navicat); no PII columns';
