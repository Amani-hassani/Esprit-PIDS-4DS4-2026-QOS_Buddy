#!/bin/bash
# Create additional Postgres databases at first boot.
# POSTGRES_MULTIPLE_DATABASES=db1,db2  →  creates db1 and db2 owned by POSTGRES_USER.

set -e

if [ -n "${POSTGRES_MULTIPLE_DATABASES:-}" ]; then
  IFS=',' read -ra dbs <<< "$POSTGRES_MULTIPLE_DATABASES"
  for db in "${dbs[@]}"; do
    db="$(echo "$db" | xargs)"
    if [ -z "$db" ]; then
      continue
    fi
    echo "[init-multi-db] creating database: $db"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
      SELECT 'CREATE DATABASE "$db"'
      WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db')\\gexec
EOSQL
  done
fi
