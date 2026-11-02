-- The SQL lab's saved queries and result snapshots (PLAN-access.md phase 5c). Idempotent: it runs on a fresh volume and postgres/sync-lab.sh runs it on one that exists.
CREATE SCHEMA IF NOT EXISTS lab;

-- A saved query: its owner, who else may use it (view: see and run it; edit: change it), and the folder it lives in (folders are the dashboards' folders: builder.folders).
CREATE TABLE IF NOT EXISTS lab.saved_queries (
    id          text        PRIMARY KEY,
    owner       text        NOT NULL,
    title       text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
    description text        NOT NULL DEFAULT '' CHECK (char_length(description) <= 400),
    sql         text        NOT NULL CHECK (char_length(sql) BETWEEN 1 AND 20000),
    folder_id   text,
    shares      jsonb       NOT NULL DEFAULT '[]',                         -- [{type: user|group, principal, permission: view|edit}]
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS saved_queries_owner ON lab.saved_queries (owner);

-- The last result of a saved query for the person who ran it. It is that person's own copy (computed under their rules: territories, role, blocked cubes), so it is never shown to anyone else,
-- whoever the query is shared with. It expires (LAB_SNAPSHOT_HOURS) and goes with the query.
CREATE TABLE IF NOT EXISTS lab.snapshots (
    query_id   text        NOT NULL REFERENCES lab.saved_queries (id) ON DELETE CASCADE,
    runner     text        NOT NULL,
    columns    jsonb       NOT NULL,
    rows       jsonb       NOT NULL,
    row_count  integer     NOT NULL,
    truncated  boolean     NOT NULL DEFAULT false,
    ms         integer     NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (query_id, runner)
);
