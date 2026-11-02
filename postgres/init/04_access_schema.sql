-- Who may see what, beyond the role (PLAN-access.md): the row-level rules the admin console edits and the auth service reads when it mints a token.
-- Idempotent: it runs on a fresh volume (this directory is the image's init directory) and postgres/sync-access.sh runs it on one that exists.
CREATE SCHEMA IF NOT EXISTS access;

-- A rule says which sales territories (regions) a person or a group may see. A person's territories are the union of the rules for them and for their groups;
-- with no rule at all, the dbt seed (rls.user_regions in StarRocks) still decides, as before.
CREATE TABLE IF NOT EXISTS access.rls_rule (
    principal_type text        NOT NULL CHECK (principal_type IN ('user', 'group')),
    principal      text        NOT NULL CHECK (char_length(principal) BETWEEN 1 AND 120),     -- the Keycloak username, or the group's name
    dimension      text        NOT NULL DEFAULT 'territory' CHECK (dimension IN ('territory')),
    "values"       text[]      NOT NULL CHECK (cardinality("values") BETWEEN 1 AND 200),
    updated_by     text        NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (principal_type, principal, dimension)
);
