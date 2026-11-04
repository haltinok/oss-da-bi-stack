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

-- The row-level dimensions (PLAN-rls-registry-db.md): which field a rule of each dimension limits, on which cubes, and whether a person with no value is denied or
-- unrestricted. Cube, the auth service and the admin console read this table once, when they start (and refuse to start on rows they could not enforce), so a
-- change here needs a restart of those three. A new database gets the default list (cube/rls_dimensions.json) from 10_rls_dimensions.sql.
CREATE TABLE IF NOT EXISTS access.rls_dimension (
    id             text        PRIMARY KEY CHECK (id ~ '^[a-z][a-z0-9_]{0,39}$'),                     -- what access.rls_rule.dimension names
    position       integer     NOT NULL DEFAULT 0,                                                     -- the order the console lists them in
    member         text        NOT NULL CHECK (member ~ '^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$'),   -- the Cube field filtered on (cube.field)
    cubes          text[]      NOT NULL CHECK (cardinality(cubes) BETWEEN 1 AND 50),                   -- every query touching one of these cubes is filtered
    when_empty     text        NOT NULL CHECK (when_empty IN ('deny', 'allow')),                       -- deny: no value, nothing from those cubes; allow: no value, no limit
    values_source  jsonb       NOT NULL DEFAULT '{"kind": "cube"}' CHECK (values_source->>'kind' IN ('seed_regions', 'list', 'cube')),   -- where the console's value list comes from
    seed           boolean     NOT NULL DEFAULT false,                                                 -- with no rule, the dbt seed (rls.user_regions) decides (territory)
    labels         jsonb       NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(labels) = 'object'),           -- the console's name for it, per language
    empty_message  text        NOT NULL DEFAULT '' CHECK (char_length(empty_message) <= 200),          -- what Cube answers a person with no value (deny)
    updated_by     text        NOT NULL DEFAULT 'install',
    updated_at     timestamptz NOT NULL DEFAULT now()
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
