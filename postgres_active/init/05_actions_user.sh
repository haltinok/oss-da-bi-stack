#!/usr/bin/env bash
# The inventory actions service's database login and its audit table (see actions/main.py).
#
# Least privilege: the login can read and INSERT into the purchasing / offer tables it writes and into the
# audit log; it has no UPDATE or DELETE anywhere, so an approved action cannot rewrite history and the log
# is append-only for it. Idempotent, so postgres_active/sync-actions.sh can run it on a volume that already
# exists (init scripts only run on a fresh volume). Skipped when ACTIONS_DB_PASSWORD is empty.
set -euo pipefail

if [ -z "${ACTIONS_DB_PASSWORD:-}" ]; then
    echo "05_actions_user: ACTIONS_DB_PASSWORD is empty, skipping"
    exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
    \getenv pw ACTIONS_DB_PASSWORD
    SELECT format('CREATE ROLE actions_writer LOGIN PASSWORD %L', :'pw')
      WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'actions_writer') \gexec
    SELECT format('ALTER ROLE actions_writer PASSWORD %L', :'pw') \gexec

    CREATE TABLE IF NOT EXISTS public.actions_log (
        id              bigserial PRIMARY KEY,
        ts              timestamptz NOT NULL DEFAULT now(),
        username        text        NOT NULL,
        role            text        NOT NULL,
        action          text        NOT NULL,
        idempotency_key text        NOT NULL UNIQUE,
        payload         jsonb       NOT NULL,
        outcome         text        NOT NULL CHECK (outcome IN ('approved', 'refused')),
        result          jsonb,
        product_ids     bigint[]    NOT NULL DEFAULT '{}',
        reason          text
    );

    GRANT USAGE ON SCHEMA public TO actions_writer;
    GRANT SELECT, INSERT ON public.purchase_order_header, public.purchase_order_detail, public.work_order,
        public.special_offer, public.special_offer_product, public.actions_log TO actions_writer;
    GRANT USAGE ON SEQUENCE public.actions_log_id_seq TO actions_writer;
EOSQL
