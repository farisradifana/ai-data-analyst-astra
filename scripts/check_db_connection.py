"""Check .env completeness and Supabase logins for both app roles.

Prints variable NAMES with filled/empty status and connection results only.
Never prints values, passwords, hosts or the project ref.

Run from project root:  python scripts/check_db_connection.py
Exit code 0 when both roles connect with the configured SSL mode, 1 otherwise.
"""
from __future__ import annotations

import os
import pathlib
import sys

from dotenv import dotenv_values

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"

DB_KEYS = ["SUPABASE_PROJECT_REF", "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME",
           "DATABASE_SCHEMA", "DATABASE_SSLMODE", "DATABASE_SSLROOTCERT", "DATABASE_USER",
           "DATABASE_PASSWORD", "REPORTING_DB_USER", "REPORTING_DB_PASSWORD"]


def report_env(env: dict) -> list[str]:
    example = dotenv_values(ROOT / ".env.example")
    empty = [k for k in example if not (env.get(k) or "").strip()]
    print(f"env: {len(example) - len(empty)}/{len(example)} keys from .env.example filled")
    for k in empty:
        print(f"  empty: {k}")
    return empty


def try_connect(env: dict, user_key: str, pw_key: str, sslmode: str, rootcert: str | None) -> bool:
    import psycopg2

    user = f"{env[user_key]}.{env['SUPABASE_PROJECT_REF']}"
    kwargs = dict(host=env["DATABASE_HOST"], port=int(env["DATABASE_PORT"]), dbname=env["DATABASE_NAME"],
                  user=user, password=env[pw_key], sslmode=sslmode, connect_timeout=15,
                  application_name="astra_connection_check")
    if rootcert:
        kwargs["sslrootcert"] = rootcert
    label = env[user_key]
    try:
        with psycopg2.connect(**kwargs) as conn, conn.cursor() as cur:
            cur.execute("select current_user, current_setting('transaction_read_only'), "
                        "current_setting('search_path'), "
                        "(select count(*) from pg_tables where schemaname = 'dataset')")
            who, ro, sp, n_tables = cur.fetchone()
            cur.execute("select count(*) from dataset.v_sales_daily")
            cur.fetchone()
            client_ssl = conn.info.ssl_in_use
        conn.close()
        print(f"  {label}: OK user={who} read_only={ro} search_path={sp} dataset_tables={n_tables} client_ssl={client_ssl}")
        return True
    except Exception as exc:  # report class + first line only, never connection params
        msg = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        for secret in (env.get(pw_key), env.get("SUPABASE_PROJECT_REF"), env.get("DATABASE_HOST")):
            if secret:
                msg = msg.replace(secret, "***")
        print(f"  {label}: FAIL {type(exc).__name__}: {msg[:200]}")
        return False


def main() -> int:
    if not ENV_FILE.exists():
        print("env: .env not found")
        return 1
    env = {k: (v or "").strip() for k, v in dotenv_values(ENV_FILE).items()}
    report_env(env)
    missing_db = [k for k in DB_KEYS if not env.get(k)]
    if missing_db:
        print(f"db: cannot test, empty: {', '.join(missing_db)}")
        return 1

    ref = env["SUPABASE_PROJECT_REF"]
    if not (len(ref) == 20 and ref.isalnum() and ref.islower()):
        print("db: SUPABASE_PROJECT_REF must be the 20-char ref only (not https://<ref>.supabase.co)")
        return 1

    sslmode = env["DATABASE_SSLMODE"]
    cert = ROOT / env["DATABASE_SSLROOTCERT"]
    rootcert = str(cert) if cert.exists() else None
    ok = True
    if rootcert is None and sslmode in ("verify-ca", "verify-full"):
        print(f"db: CA cert missing at {env['DATABASE_SSLROOTCERT']}; {sslmode} cannot run")
        print("db: fallback check with sslmode=require (encrypted, server NOT verified) to test passwords only")
        sslmode, ok = "require", False
    else:
        print(f"db: sslmode={sslmode}")
    for user_key, pw_key in (("DATABASE_USER", "DATABASE_PASSWORD"), ("REPORTING_DB_USER", "REPORTING_DB_PASSWORD")):
        ok = try_connect(env, user_key, pw_key, sslmode, rootcert) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())
