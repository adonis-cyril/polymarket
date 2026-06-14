#!/usr/bin/env bash
# Local PostgreSQL setup for macOS Homebrew (postgresql@16). Matches docker-compose credentials.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_BIN="${PG_BIN:-/opt/homebrew/opt/postgresql@16/bin}"
export PATH="$PG_BIN:$PATH"

DB_USER="${DB_USER:-polymarket}"
DB_PASS="${DB_PASS:-polymarket}"
DB_NAME="${DB_NAME:-polymarket}"

if ! command -v psql >/dev/null; then
  echo "postgresql@16 not found. Install: brew install postgresql@16" >&2
  exit 1
fi

if ! brew services list 2>/dev/null | grep -q 'postgresql@16.*started'; then
  echo "Starting postgresql@16..."
  brew services start postgresql@16
  sleep 2
fi

echo "Ensuring role and database ${DB_NAME}..."
psql -d postgres -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';
  ELSE
    ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\\gexec
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

echo "Applying schema from scripts/init_db.sql..."
psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$ROOT/scripts/init_db.sql"

echo "Granting ownership to ${DB_USER}..."
psql -d "$DB_NAME" -v ON_ERROR_STOP=1 <<SQL
ALTER DATABASE ${DB_NAME} OWNER TO ${DB_USER};
DO \$\$
DECLARE r record;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
  LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO ${DB_USER}', r.tablename);
  END LOOP;
  FOR r IN SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public'
  LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO ${DB_USER}', r.sequence_name);
  END LOOP;
END \$\$;
GRANT ALL ON SCHEMA public TO ${DB_USER};
SQL

echo "Done. Test with: psql \"postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}\" -c 'SELECT 1'"
