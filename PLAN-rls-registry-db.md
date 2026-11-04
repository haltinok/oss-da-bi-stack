# Plan: the row-level dimension registry in the database

Status: **done** (written and built 2026-11-04, one PR). Follows [`PLAN-rls-dimensions.md`](PLAN-rls-dimensions.md), which made the dimensions a file (`cube/rls_dimensions.json`) instead of code.

## Goal
The list of row-level dimensions (which field, on which cubes, deny or allow when a person has no value) lives in Postgres, `access.rls_dimension`, next to the rules that use it. Cube, the auth service and the admin console read it **once, when they start**. A change to the list is an update in the database and a restart of those services; no file is edited or deployed.

## What does not change
- The rules themselves (`access.rls_rule`, who sees which values) are edited in the console and apply at the next sign-in, as before.
- How Cube enforces a dimension: `member in (values)` on every query that touches one of its cubes; dimensions ANDed, the values of one ORed; `when_empty: deny` denies.
- A dimension's field must still be in the sales rollups to stay fast. Moving the list to the database does not change that; see "Adding a dimension".

## Decisions
1. **Read at startup, fail closed.** When a service is configured to read the access database and the read fails, or the rows are not a valid registry (an unknown `when_empty`, a member that is not `cube.field`, no cubes, duplicate ids, **no rows at all**), the service does not start. It retries for a while first (Postgres may start after it); the container's restart policy retries after that. A Cube that started with half a registry, or none, would leave rows open; a Cube that is down is visible and leaks nothing.
2. **Cube reads it synchronously while `cube.js` loads**, through a small child process (`cube/rls_registry_load.js`, using the `pg` client the Cube image already ships). `queryRewrite` stays synchronous and never waits on a database. Cube gets its own login, `access_cube`, that can only `SELECT` from `access.rls_dimension`.
3. **The file stays as the default.** `cube/rls_dimensions.json` (and its copies in `auth/` and `admin/`) is used when a service has no access-database login configured (the lean demo that starts without Postgres, the unit tests). It is also what a new database is seeded with: `postgres/init/10_rls_dimensions.sql` is generated from it (`scripts/rls_dimensions_sql.py`; a test fails when they differ). The seed inserts only missing ids, so it never overwrites an edit made in the database.
4. **The services must agree.** Each service computes a **registry version**: a hash of the canonical form of the list. The auth service puts it in the Cube token (`rls_version`); Cube refuses a token whose version is not its own (403, "the row-level dimensions changed: restart the auth service and Cube together"). Without this, restarting auth but not Cube after adding a dimension would give tokens with values for a dimension Cube does not filter on. A token without `rls_version` (from an auth service older than this change) is accepted, so an upgrade does not lock people out for the 15 minutes their tokens live.
5. **The console shows where the list came from** (database or default file) and its version, so an administrator can see whether the services agree.

## Changes
- `postgres/init/04_access_schema.sql`: `access.rls_dimension` (id, position, member, cubes, when_empty, values_source, seed, labels, empty_message, updated_by, updated_at), with checks.
- `postgres/init/10_rls_dimensions.sql` (generated) and `postgres/sync-access.sh` runs it; `05_access_users.sh`: `SELECT` on the table for `access_admin` and `access_auth`, the `access_cube` login (`CUBE_ACCESS_PG_PASSWORD`).
- `auth/rls_registry.py` and `admin/rls_registry.py` (identical copies, like `access_resolve.py`): validate, load from the database or the file, canonical form and version. A JS mirror of the validation and the version in `cube/cube.js`; a test checks the versions agree.
- `auth/main.py`, `admin/main.py`, `cube/cube.js`: read the registry at startup; the token carries `rls_version`; Cube checks it.
- Compose and `.env.example`: Cube's access-database settings. Docs: `docs/admin.md`, `docs/deploy-demo.md` (the update steps), README.

## Adding a dimension, after this
1. Make sure the field is a dimension of every rollup of the cubes it will filter (the model, `cube/model/cubes/*.yml`), or those queries fall back to the raw tables.
2. `INSERT INTO access.rls_dimension ...` (the docs give the statement), and starter rules if `when_empty` is `deny`.
3. Restart `cube` (and `cube-250m`), `auth` and `admin`.

## Not in this plan
- Editing the dimension list in the console. With startup loading it would need a restart button or a reload signal; it can come later on top of this table.
- Checking a database row against the Cube model at startup (does the member exist, does each cube join it?). Cube fails a query whose member it cannot join, so a bad row denies rather than leaks; the CI test still checks the default file.
