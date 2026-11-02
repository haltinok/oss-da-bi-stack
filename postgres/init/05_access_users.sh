#!/usr/bin/env bash
# The logins of the access schema (04_access_schema.sql). Least privilege: the admin console may read and write the rules; the auth service may only read them.
# Idempotent (postgres/sync-access.sh runs it on a volume that exists). A login whose password variable is empty is skipped: the service then runs without rules.
set -euo pipefail

for pair in access_admin:ADMIN_DB_PASSWORD access_auth:AUTH_PG_PASSWORD; do
    role=${pair%%:*}; var=${pair##*:}
    if [ -z "${!var:-}" ] || [ "${!var}" = "REPLACE_ME" ]; then
        echo "05_access_users: $var is empty, skipping $role"
        continue
    fi
    export ACCESS_ROLE=$role ACCESS_PW=${!var}
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
        \getenv role ACCESS_ROLE
        \getenv pw ACCESS_PW
        SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'role', :'pw')
          WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role') \gexec
        SELECT format('ALTER ROLE %I PASSWORD %L', :'role', :'pw') \gexec
        SELECT format('GRANT USAGE ON SCHEMA access TO %I', :'role') \gexec
EOSQL
done
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
    REVOKE ALL ON SCHEMA access FROM PUBLIC;
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'access_admin') THEN
        GRANT USAGE ON SCHEMA access TO access_admin;
        GRANT SELECT, INSERT, UPDATE, DELETE ON access.rls_rule TO access_admin;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'access_auth') THEN
        GRANT USAGE ON SCHEMA access TO access_auth;
        GRANT SELECT ON access.rls_rule TO access_auth;
      END IF;
    END $$;
EOSQL
echo "05_access_users: the access logins are in place"
