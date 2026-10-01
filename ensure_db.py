"""
Create the PostgreSQL database if it does not already exist.

Reads the same .env values as Django, connects to the default 'postgres'
maintenance database, and creates DB_NAME when missing. Safe to run every
time — it does nothing if the database is already there.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def load_env():
    env = {}
    f = BASE_DIR / ".env"
    if f.exists():
        for raw in f.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main():
    env = load_env()
    name = env.get("DB_NAME", "sopd_db")
    user = env.get("DB_USER", "postgres")
    password = env.get("DB_PASSWORD", "postgres")
    host = env.get("DB_HOST", "127.0.0.1")
    port = env.get("DB_PORT", "5432")

    try:
        import psycopg2
        from psycopg2 import sql
    except ImportError:
        print("psycopg2 not installed yet — skipping DB check (run again after install).")
        return 0

    try:
        conn = psycopg2.connect(dbname="postgres", user=user,
                                password=password, host=host, port=port)
    except Exception as exc:
        print("Could not connect to PostgreSQL server.")
        print(f"  {exc}")
        print("  → Make sure PostgreSQL is installed and running, and that the")
        print("    DB_USER / DB_PASSWORD in your .env file are correct.")
        return 1

    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (name,))
        if cur.fetchone():
            print(f'Database "{name}" already exists.')
        else:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            print(f'Database "{name}" created.')
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
