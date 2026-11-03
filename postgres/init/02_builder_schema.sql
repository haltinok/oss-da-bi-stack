-- Saved dashboards of the dashboard builder (builder/store.py): who saved what, who may open it, and the last versions of each.
-- Idempotent: it runs on a fresh volume (this directory is the image's init directory) and postgres/sync-builder.sh runs it on one that exists.
CREATE SCHEMA IF NOT EXISTS builder;

CREATE TABLE IF NOT EXISTS builder.saved_dashboards (
    id           text PRIMARY KEY,
    owner        text        NOT NULL,                              -- the Keycloak username
    owner_role   text        NOT NULL,
    title        text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
    description  text        NOT NULL DEFAULT '',
    yaml         text        NOT NULL CHECK (char_length(yaml) <= 30000),   -- the spec, validated for owner_role when it was saved
    visibility   text        NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'roles', 'everyone')),
    shared_roles text[]      NOT NULL DEFAULT '{}',                 -- used when visibility = 'roles'
    version      integer     NOT NULL DEFAULT 1,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS saved_dashboards_owner ON builder.saved_dashboards (owner);

CREATE TABLE IF NOT EXISTS builder.saved_versions (
    dashboard_id text        NOT NULL REFERENCES builder.saved_dashboards (id) ON DELETE CASCADE,
    version      integer     NOT NULL,
    title        text        NOT NULL,
    yaml         text        NOT NULL,
    saved_by     text        NOT NULL,
    saved_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dashboard_id, version)
);

-- Sharing with people and groups, folders, and a trash (PLAN-access.md phase 3). Idempotent additions to the tables above.
ALTER TABLE builder.saved_dashboards ADD COLUMN IF NOT EXISTS shares     jsonb       NOT NULL DEFAULT '[]';   -- [{type: user|group, principal, permission: view|edit}]
ALTER TABLE builder.saved_dashboards ADD COLUMN IF NOT EXISTS folder_id  text;
ALTER TABLE builder.saved_dashboards ADD COLUMN IF NOT EXISTS deleted_at timestamptz;                       -- set: in the trash (kept 30 days, then purged)

CREATE TABLE IF NOT EXISTS builder.folders (
    id         text        PRIMARY KEY,
    name       text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
    owner      text        NOT NULL,                                                                          -- the Keycloak username
    shares     jsonb       NOT NULL DEFAULT '[]',                                                             -- who else may see (view) or change (edit) what is in it
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS saved_dashboards_folder ON builder.saved_dashboards (folder_id);

-- Roles say what a person may do now (admin, editor, viewer): a dashboard shared with the old data roles is shared with editors (idempotent: nothing changes once it has run).
UPDATE builder.saved_dashboards
   SET shared_roles = ARRAY(SELECT DISTINCT CASE WHEN r IN ('manager', 'rep', 'purchasing', 'marketing') THEN 'editor' ELSE r END FROM unnest(shared_roles) AS r ORDER BY 1)
 WHERE shared_roles && ARRAY['manager', 'rep', 'purchasing', 'marketing'];
