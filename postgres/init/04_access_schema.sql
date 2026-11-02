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

-- Datasets: named sets of cubes. A cube that is in at least one dataset is "governed": only people with a grant on a dataset that contains it may read it (admins always can).
-- A cube in no dataset is governed by the role rules alone, as before. So nothing changes until a dataset is created, and a grant can only narrow what the role allows.
CREATE TABLE IF NOT EXISTS access.dataset (
    id          text        PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9_-]{0,39}$'),
    name        text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
    description text        NOT NULL DEFAULT '' CHECK (char_length(description) <= 400),
    cubes       text[]      NOT NULL CHECK (cardinality(cubes) BETWEEN 1 AND 100),
    updated_by  text        NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Who may use what. object_type is general on purpose (folders and dashboards come in phase 3); `view` is the only permission so far.
CREATE TABLE IF NOT EXISTS access.grant (
    object_type    text NOT NULL CHECK (object_type IN ('dataset', 'folder', 'dashboard')),
    object_id      text NOT NULL,
    principal_type text NOT NULL CHECK (principal_type IN ('user', 'group', 'role')),
    principal      text NOT NULL CHECK (char_length(principal) BETWEEN 1 AND 120),
    permission     text NOT NULL DEFAULT 'view' CHECK (permission IN ('view')),
    granted_by     text NOT NULL,
    granted_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type, object_id, principal_type, principal)
);
