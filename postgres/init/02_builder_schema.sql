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
