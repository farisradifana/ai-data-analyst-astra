# PostgreSQL schema rules

- **One schema** for the platform (`dataset`). No objects in `public`.
- **Migrations**: `sql/migrations/<UTC yyyymmddHHMMSS>_<name>.sql`, applied in order, never edited after they are
  applied. A fix is a new migration.
- **Destructive SQL** (DROP, TRUNCATE, DELETE/UPDATE without a key filter, `db reset`), grants, RLS and role changes:
  write them, show them, and apply only after the user approves in the current conversation. Guard a DROP with a
  check that the object is empty or unused.
- **RLS enabled on every table**, with explicit policies per role. Verify `tables_without_rls = 0`.
- **Roles**: one writer for the ETL, one read-only reporting role. Passwords are set by the user in the SQL editor
  (`ALTER ROLE ... PASSWORD`), never through chat or files.
- **PII**: revoke column SELECT on names, emails, phones, raw quarantine records from the reporting role;
  reporting views expose only non-PII columns.
- **Views** for consumers: `CREATE VIEW ... WITH (security_invoker = true)` so the caller's privileges apply.
- **Constraints**: typed columns, CHECK ranges and allowed values, FKs between core tables, all `convalidated`.
  The ETL validates the same rules first, so a constraint violation means a code bug, not bad data.
- **Generated columns** for derived money values (e.g. net amount) keep the logic in one place.

## Read-only integrity checks (safe to run any time)

```sql
-- constraints and RLS
SELECT contype, count(*) FILTER (WHERE convalidated) AS valid, count(*) AS total
FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname = 'dataset' AND contype IN ('f','c') GROUP BY contype;

SELECT count(*) AS tables_without_rls FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'dataset' AND c.relkind = 'r' AND NOT c.relrowsecurity;

-- the reporting role must not write
SELECT bool_or(has_table_privilege('astra_reporting', c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE'))
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'dataset' AND c.relkind = 'r';

-- runs left RUNNING mean a crash
SELECT status, count(*) FROM dataset.etl_run GROUP BY status;
```

Reconciliation per table: `sum(source_file.rows_read) = table rows + open quarantine rows + distinct
DUPLICATE_DROPPED archive rows`. Rows dropped with `fix drop` count on the right side as well.
