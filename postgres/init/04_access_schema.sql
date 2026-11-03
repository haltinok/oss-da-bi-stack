-- Who may see what, beyond the role (PLAN-access.md): the row-level rules the admin console edits and the auth service reads when it mints a token.
-- Idempotent: it runs on a fresh volume (this directory is the image's init directory) and postgres/sync-access.sh runs it on one that exists.
CREATE SCHEMA IF NOT EXISTS access;

-- A rule says which values of one dimension (cube/rls_dimensions.json: territory, ...) a person or a group may see. A person's values are the union of the rules for them and for their groups;
-- for the territory dimension, with no rule at all, the dbt seed (rls.user_regions in StarRocks) still decides, as before.
CREATE TABLE IF NOT EXISTS access.rls_rule (
    principal_type text        NOT NULL CHECK (principal_type IN ('user', 'group')),
    principal      text        NOT NULL CHECK (char_length(principal) BETWEEN 1 AND 120),     -- the Keycloak username, or the group's name
    dimension      text        NOT NULL DEFAULT 'territory' CHECK (dimension ~ '^[a-z][a-z0-9_]{0,39}$'),      -- an id from cube/rls_dimensions.json (admin and auth check it there)
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
    cubes       text[]      NOT NULL DEFAULT '{}',                           -- whole cubes that need a grant
    members     text[]      NOT NULL DEFAULT '{}',                           -- single fields (cube.member, e.g. internet_sales.gross_profit) that need a grant, wherever else the cube is open
    CONSTRAINT dataset_has_content CHECK (cardinality(cubes) + cardinality(members) BETWEEN 1 AND 300),
    updated_by  text        NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Who may use what. object_type is general on purpose; `view` reads the dataset's cubes, `lab` also opens the SQL lab (a grant on any dataset with `lab` is what turns the lab on for a person).
CREATE TABLE IF NOT EXISTS access.grant (
    object_type    text NOT NULL CHECK (object_type IN ('dataset', 'folder', 'dashboard')),
    object_id      text NOT NULL,
    principal_type text NOT NULL CHECK (principal_type IN ('user', 'group', 'role')),
    principal      text NOT NULL CHECK (char_length(principal) BETWEEN 1 AND 120),
    permission     text NOT NULL DEFAULT 'view' CHECK (permission IN ('view', 'lab')),                              -- lab: view, and may use the SQL lab
    granted_by     text NOT NULL,
    granted_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (object_type, object_id, principal_type, principal)
);

-- An install that has the table from before `lab` existed: widen the check (idempotent).
ALTER TABLE access."grant" DROP CONSTRAINT IF EXISTS grant_permission_check;
ALTER TABLE access."grant" ADD CONSTRAINT grant_permission_check CHECK (permission IN ('view', 'lab'));

-- An install that has the table from before datasets could hold single fields: add the column and widen the check (idempotent).
ALTER TABLE access.dataset ADD COLUMN IF NOT EXISTS members text[] NOT NULL DEFAULT '{}';
ALTER TABLE access.dataset ALTER COLUMN cubes SET DEFAULT '{}';
ALTER TABLE access.dataset DROP CONSTRAINT IF EXISTS dataset_cubes_check;
ALTER TABLE access.dataset DROP CONSTRAINT IF EXISTS dataset_has_content;
ALTER TABLE access.dataset ADD CONSTRAINT dataset_has_content CHECK (cardinality(cubes) + cardinality(members) BETWEEN 1 AND 300);

-- An install that has the table from before there could be more than one dimension: the check allowed only 'territory' (idempotent).
ALTER TABLE access.rls_rule DROP CONSTRAINT IF EXISTS rls_rule_dimension_check;
ALTER TABLE access.rls_rule DROP CONSTRAINT IF EXISTS rls_rule_dimension_id;
ALTER TABLE access.rls_rule ADD CONSTRAINT rls_rule_dimension_id CHECK (dimension ~ '^[a-z][a-z0-9_]{0,39}$');
