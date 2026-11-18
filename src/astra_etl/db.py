"""Database connection from .env (Supabase Session pooler, verify-full SSL). Never logs values."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_env() -> dict[str, str]:
    from dotenv import dotenv_values  # imported here so modules that use only ROOT need no python-dotenv

    env_file = ROOT / ".env"
    if not env_file.exists():
        raise RuntimeError(".env not found")
    return {k: (v or "").strip() for k, v in dotenv_values(env_file).items()}


def connect(role: str = "analyst"):
    """role 'analyst' -> DATABASE_USER (writer); 'reporting' -> REPORTING_DB_USER (read-only)."""
    import psycopg2

    env = load_env()
    user_key, pw_key = (("DATABASE_USER", "DATABASE_PASSWORD") if role == "analyst"
                        else ("REPORTING_DB_USER", "REPORTING_DB_PASSWORD"))
    ref = env.get("SUPABASE_PROJECT_REF", "")
    if not (len(ref) == 20 and ref.isalnum()):
        raise RuntimeError("SUPABASE_PROJECT_REF must be the 20-char project ref")
    sslmode = env.get("DATABASE_SSLMODE") or "verify-full"
    cert = ROOT / env.get("DATABASE_SSLROOTCERT", "secrets/supabase-ca.crt")
    if sslmode in ("verify-ca", "verify-full") and not cert.exists():
        raise RuntimeError(f"CA certificate not found at {env.get('DATABASE_SSLROOTCERT')}")
    return psycopg2.connect(
        host=env["DATABASE_HOST"], port=int(env.get("DATABASE_PORT") or 5432),
        dbname=env.get("DATABASE_NAME") or "postgres", user=f"{env[user_key]}.{ref}",
        password=env[pw_key], sslmode=sslmode, sslrootcert=str(cert),
        connect_timeout=20, application_name="astra_etl")
