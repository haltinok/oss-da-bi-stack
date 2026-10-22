#!/usr/bin/env bash
# The inventory actions service's database login and its audit table (see actions/main.py).
#
# Least privilege: the login can read and INSERT into the purchasing / offer tables it writes and into the
# audit log; it has no UPDATE or DELETE on those, so an approved action cannot rewrite history and the log
# is append-only for it. The one exception is the decision columns of public.proposals. Idempotent, so postgres_active/sync-actions.sh can run it on a volume that already
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
        outcome         text        NOT NULL,
        result          jsonb,
        product_ids     bigint[]    NOT NULL DEFAULT '{}',
        reason          text
    );

    -- 'drafted' = the proposal agent wrote a proposal (see public.proposals); 'approved' / 'refused' are human actions.
    ALTER TABLE public.actions_log DROP CONSTRAINT IF EXISTS actions_log_outcome_check;
    ALTER TABLE public.actions_log ADD CONSTRAINT actions_log_outcome_check CHECK (outcome IN ('approved', 'refused', 'drafted'));

    -- What the agent drafted and what a person did with it. The agent can only INSERT (through the service);
    -- approving or dismissing is a human role and updates only the decision columns.
    CREATE TABLE IF NOT EXISTS public.proposals (
        id            bigserial PRIMARY KEY,
        created_at    timestamptz NOT NULL DEFAULT now(),
        run_id        text        NOT NULL,
        seq           integer     NOT NULL,
        created_by    text        NOT NULL,
        kind          text        NOT NULL CHECK (kind IN ('purchase_order', 'work_order', 'campaign')),
        title         text        NOT NULL,
        rationale     text        NOT NULL,
        payload       jsonb       NOT NULL,
        numbers       jsonb       NOT NULL,
        status        text        NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'dismissed')),
        decided_by    text,
        decided_at    timestamptz,
        action_log_id bigint,
        UNIQUE (run_id, seq)
    );

    GRANT USAGE ON SCHEMA public TO actions_writer;
    GRANT SELECT, INSERT ON public.purchase_order_header, public.purchase_order_detail, public.work_order,
        public.special_offer, public.special_offer_product, public.actions_log TO actions_writer;
    GRANT SELECT, INSERT ON public.proposals TO actions_writer;
    GRANT UPDATE (status, decided_by, decided_at, action_log_id) ON public.proposals TO actions_writer;
    GRANT USAGE ON SEQUENCE public.actions_log_id_seq, public.proposals_id_seq TO actions_writer;
EOSQL
