# ETL run summary (dry-run)

Generated: 2026-11-18T02:28:07+00:00  
Run id: n/a (dry run)

New files are read once. Quarantine rows are rechecked on every run.

| Table | New files | Read | Loaded | Quarantined | Duplicate | Rechecked | Graduated | In quarantine after |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| customers | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| employees | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| suppliers | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| products | 0 | 0 | 0 | 0 | 0 | 69 | 0 | 69 |
| sales_transactions | 0 | 0 | 0 | 0 | 0 | 3,996 | 0 | 3,996 |
| service_orders | 0 | 0 | 0 | 0 | 0 | 387 | 0 | 387 |
| procurement | 0 | 0 | 0 | 0 | 0 | 599 | 0 | 599 |
| inventory | 0 | 0 | 0 | 0 | 0 | 593 | 0 | 593 |
| expenses | 0 | 0 | 0 | 0 | 0 | 120 | 0 | 120 |
| attendance | 0 | 0 | 0 | 0 | 0 | 150 | 0 | 150 |
| **TOTAL** | | **0** | **0** | **0** | **0** | **5,914** | **0** | **5,914** |

Rules of the rows in quarantine after the run:

- products: NEGATIVE_AMOUNT 32, REQUIRED_FIELD_MISSING 37
- sales_transactions: NUMERIC_VALUE_INVALID 300, ORPHAN_KEY_NOT_IN_SOURCE 751, ORPHAN_PARENT_QUARANTINED 2945
- service_orders: ORPHAN_KEY_NOT_IN_SOURCE 138, ORPHAN_PARENT_QUARANTINED 249
- procurement: ORPHAN_KEY_NOT_IN_SOURCE 191, ORPHAN_PARENT_QUARANTINED 408
- inventory: NUMERIC_VALUE_INVALID 37, ORPHAN_PARENT_QUARANTINED 493, REQUIRED_FIELD_MISSING 63
- expenses: NEGATIVE_AMOUNT 47, REQUIRED_FIELD_MISSING 73
- attendance: ORPHAN_KEY_NOT_IN_SOURCE 73, REQUIRED_FIELD_MISSING 77
