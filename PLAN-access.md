# Plan: users, access, folders, a home page and a SQL lab

Status: **draft, written 2026-11-02, nothing built.** Phases 1 to 5, one PR each (phase 5 in three). Open questions for the product owner are at the end; phase 1 does not depend on any of them.

## Why
The dashboard side is finished: a person can describe, write or click a dashboard into existence. What is missing is the layer around it that lets a *team* use it:
administrators who can add people and take access away without editing a script, ways to share work with a person or a group (not only a role), a place to keep work in, a
start page, and a SQL lab for analysts who need rows rather than charts. The product is for small and medium businesses (open source plus paid support), so the
answer is a small, understandable system, not an enterprise IAM suite.

## What the code gives us (reviewed 2026-11-02)
- **Identity is Keycloak.** One realm (`keycloak/realm-spike.json`), clients `dashboard` and `inventory-agent`, realm roles `admin, manager, rep, purchasing, marketing, agent`. Users are made by
  `keycloak/sync-users.sh`; there is no screen.
- **One role per user, fixed in code.** `auth/main.py` picks the highest of `ROLE_ORDER`; `cube/cube.js` (`ROLE_CUBES`, `TERRITORY_ROLES`, profit rules) and the builder's catalog filter by that role.
  A role is therefore both "what kind of user" and "which data". Adding a role means editing code.
- **Row-level security is a table.** `auth` reads `rls.user_regions` (built by dbt from the seed `dim_user_territory`), puts `territories` in a 15-minute Cube JWT, and Cube's `queryRewrite`
  applies it. Changing someone's regions means editing a CSV and running dbt.
- **Saved dashboards** (`builder/saved.py`, `store.py`, Postgres `builder.saved_dashboards`): owner, versions, `visibility` of `private | roles | everyone` and `shared_roles`. An admin can open
  and delete any; only the owner changes the YAML. The list page (`render/list.js`) has search, tags and a TR/EN dictionary.
- **No SQL path for people.** Everything goes through Cube; Cube is where row-level security lives, **StarRocks itself knows nothing about users**.
- Services already in compose: `auth`, `builder`, `actions`, `dashboard-cube` (static pages + proxy), `cube`, `starrocks-*`, `keycloak`, Postgres (`oss_postgres`).

## Decisions
- **Keycloak stays the identity store; we do not write a user database.** Passwords, deactivation, required actions, sessions, later LDAP/SSO federation are all things it does. The
  admin console is a thin, opinionated screen over Keycloak's admin REST API.
- **Our own Postgres holds *permissions on our objects*.** A new schema `access` (grants, folders, datasets, RLS rules) next to `builder`. Keycloak says *who someone is and which groups
  they are in*; `access` says *what that may touch*. Keeping them apart means Keycloak can be swapped for another OIDC provider.
- **Groups are the unit of sharing.** Users belong to groups (Keycloak groups, carried in the token as a `groups` claim). A grant names a user, a group or a role.
- **Roles stay, as the coarse level.** `admin / manager / rep ...` keep their meaning in Cube; grants *narrow or extend within* them (see open question 1). Nothing that works today is removed in phase 1 to 3.
- **One backend service for the console: `admin/`** (FastAPI, like `auth` and `builder`), reached through the same nginx as the others, with a Keycloak service-account client (`admin-console`,
  client-credentials, only the realm-management roles it needs). The browser never holds a Keycloak admin token.
- **Only an admin sees the console.** The service checks the caller's token role itself; hiding the menu is a convenience.
- **Same craft as the designer:** plain JS pages in `dashboard/static`, no framework; the logic in testable modules (node tests), the pages in Playwright tests against the mock stack, the backend
  in pytest; every change written to the audit log the builder already uses; English and Turkish strings from the start.
- **Every phase is shippable and reversible.** A phase that changes stored data ships a migration that can be run twice and a note on how to undo it.

## Phase 1: users, groups and roles (the admin console)
What an admin can do, on a new page `/admin` (linked from the header for admins only):
- **Users:** list with search and filter (active / inactive, role, group); create (username, email, name, role, groups, *temporary password* the user must change at first login);
  edit; **deactivate / activate** (Keycloak `enabled`); **set password** (temporary or permanent) and **reset password** (sets a temporary one and, when the realm has SMTP,
  sends Keycloak's own "update password" email); delete (a second, typed confirmation; the interface prefers deactivate and says why).
- **Groups:** create, rename, delete, add and remove members. One level of nesting is *not* in this phase.
- **Roles:** assign the existing realm role to a user (one, as today). Creating new roles is not in this phase.
- **Safeguards in the backend, not only the page:** the last active admin cannot be deactivated, deleted or demoted; you cannot deactivate yourself; every change is audited
  (who, what, which user, when); a deactivated user's Keycloak sessions are ended so the refresh stops (their Cube token still lives up to 15 minutes: said in the docs).
- **Token:** a Keycloak group mapper adds `groups` to the access token; `auth` passes it on in the Cube JWT (Cube ignores it until phase 2).
**Built (2026-11-02):** `admin/` (FastAPI: `main.py` routes and rules, `keycloak.py` the admin-API client; tests against an in-memory fake), the `admin-console` client and a `groups` mapper on the `dashboard` client (`realm-spike.json` for new installs, `keycloak/sync-users.sh` for existing ones), `auth` passes `groups` into the Cube token, the page `/admin/` (`dashboard/static/admin.html`, `render/admin.js`, English and Turkish), Caddy route `/admin-api`, compose service `admin`, `ADMIN_CLIENT_SECRET`. User guide: `docs/admin.md`. Verified against the real Keycloak: create, edit, group, password, deactivate (a deactivated person cannot sign in), delete, the self and last-admin refusals, and `groups` in the next token. A reset by email returns Keycloak's own refusal when the realm has no sender address configured. Tests: pytest with a fake Keycloak (the pattern the `auth` tests use); a Playwright pass over the page on the mock stack; one real-Keycloak smoke job in CI if the
existing `starrocks-e2e` can host it cheaply, otherwise a documented manual check.

## Phase 2: datasets, row-level rules and grants
Split in two PRs. **2a (row-level rules, built 2026-11-02):** `access.rls_rule` (Postgres, `postgres/init/04_access_schema.sql`, logins `access_admin` read/write and `access_auth` read-only, `05_access_users.sh`, `postgres/sync-access.sh`);
the `auth` service reads the rules at token time (union over the person and their groups, else the dbt seed; fails closed when the rules database cannot be read); the admin service has `/rls/rules` and `/rls/preview/{user}`;
the console has a **Row rules** tab with the preview. A rule replaces the seed for that person; rules follow a group's rename and go with a deleted group or person. Decisions taken with the plan's recommendations
(2026-11-02): grants only narrow, one role per person, a deleted person's dashboards transfer (phase 3). **2b (datasets and grants, built 2026-11-02):** `access.dataset` and the general `access.grant` (object_type dataset|folder|dashboard; only datasets used so far); a cube in a dataset is governed (needs a grant), a cube in none is untouched, so nothing changes until a dataset exists and a grant can only narrow; `access_resolve.blocked_cubes` (one file shipped in auth/, builder/, admin/, kept identical by a test); `auth` puts `blocked_cubes` in the Cube token and `cube/cube.js` refuses queries that touch one; the builder leaves them out of the catalog; the console has a Datasets tab; the preview lists a person's blocked cubes. Original design notes:

- **The `access` schema** (migration, idempotent): `access.grant (principal_type user|group|role, principal, object_type dataset|folder|dashboard, object_id, permission view|edit|manage)`,
  `access.dataset (id, name, description, cubes[])`, `access.rls_rule (principal_type, principal, dimension, values[])`.
- **Datasets:** a named set of cubes ("Sales", "Inventory", "Finance"). The catalog the builder and the designer offer, and what Cube allows, becomes *role's cubes ∩ datasets the user has a grant on*
  (admins: everything). Seeded so that today's behaviour is unchanged.
- **Row-level rules:** replace the dbt seed as the source of territories. `auth` reads the rules for the user *and their groups* (union) and mints the same `territories` claim, so
  Cube's `queryRewrite` is unchanged. The seed's rows are imported once; the seed stays as a fallback until a release says otherwise. A rule may name any dimension later; territories first.
- **Screens in the console:** Datasets (who can use each), Row rules (per user or group, with a "what will this person see" preview that runs the same query path as the dashboards).
- Tests: the `auth` tests gain group union and the seed fallback; a regression test that every existing role keeps exactly its current catalog.

## Phase 3: folders and dashboard management
**Built (2026-11-03), with one deviation:** sharing, folders and the trash live in the builder's own schema and service (`builder.folders`; `shares`, `folder_id`, `deleted_at` on `saved_dashboards`; routes `/folders`, `/trash`, `/transfer`, and `shares`/`folder_id`/`owner` on `PUT /saved/{id}`), not in `access.grant`, because
the builder already owns dashboards, its login can write them, and giving it write access to a general grants table would have let it write dataset grants too. Rules: view or edit shares to people and groups on a dashboard or a folder; edit changes the YAML and the title,
the owner (or an admin) changes sharing, folder and owner; delete goes to a 30-day trash; an admin can hand a person's dashboards over (the console's delete-person dialog does it by default). Folders are flat (one level). The list page has the folder view,
the Share dialog, the trash; names are typed (the builder cannot look people up). Original plan:
- **Folders** (the "panes"): `access.folder (id, name, parent_id null, owner)`, one nesting level at first. A folder holds dashboards now and SQL-lab queries later. A grant on a folder
  covers what is inside it; a grant on a dashboard covers that one.
- **Dashboards:** the `visibility / shared_roles` pair becomes grants (migration maps `private`, `roles`, `everyone` onto them and the old columns stay readable for one release). New: **share with a
  user or a group** (view or edit), **change ownership** (owner or admin; the new owner needs edit rights on the dataset), **move to a folder**, **delete** and **restore** from a short-lived trash.
- The existing rules stay: the spec is validated *for the opener's role* each time it is opened, only someone with edit changes the YAML, versions are kept.
- **UI:** the dashboards list gets a folder tree and a "Shared with me" view; a share dialog (people, groups, level) on each dashboard; a folder's page to manage who can reach it.
- Tests: the saved-dashboard rules (`builder/tests`) extend to grants; Playwright for the share dialog and the folder tree.

## Phase 4: the home page
**Built (2026-11-03):** `/home/` (`dashboard/static/home.html`, `render/home.js`, English and Turkish): launcher, "pick up where you left off" (a per-browser list kept in `localStorage`, `lib/recent.js`, written when a dashboard opens), shared with you, your dashboards and folders,
samples, one search over all of them, admin link for admins. It is a new page, not a replacement for `/` (the live sales dashboard stays there: its tests and the demo's address depend on it); changing `/` to the start page is one nginx line if wanted. "SQL lab" gets a launcher card in phase 5. Original plan:
- `/` after sign-in: *recent*, *shared with me*, *my folders*, and a launcher: new dashboard (describe / design), SQL lab (when it exists), and, for admins, the console. Everything shown is
  what the user can reach; empty states say what to do next. Reuses the list page's search.
- Small by design; it is mostly a query over phase 3's grants. It waits for them so it does not have to be redone.

## Phase 5: the SQL lab (three PRs; the risky one, so it comes last)
The problem to solve first: **row-level security is in Cube, not in StarRocks**, so a raw SQL box would walk around it. Decision for 5a, after a short spike (to be recorded here before
anything user-facing ships): the lab runs only **read-only `SELECT` over dataset views**, never over raw tables, and the rules of phase 2 are applied by the lab service before the query reaches StarRocks
(the leading option is to parse the statement, refuse anything but a single SELECT over allowed views, and wrap each view in its row filter); a StarRocks account with SELECT only on the lab
views is the second line of defence. If the spike shows parsing is not trustworthy enough, the fallback is per-user StarRocks accounts with row policies.
- **5a, run:** a `lab/` service; editor page (plain JS; schema browser limited to the user's datasets; tabs; history); limits (statement timeout, row cap, concurrency per user); every statement in the audit log;
  results grid with sort and copy.
- **5b, export:** CSV and Excel, streamed, same limits and audit; the Excel writer the dashboards already use.
- **5c, keep results:** *saved queries* (owned, shareable like dashboards, living in folders) and **cached results**: a result written to a table in a lab schema with a time-to-live, readable by
  whoever the query is shared with. A **materialized view** option comes after the cache works, as "refresh this on a schedule", and only for queries that pass the same checks; this is the blurry part and is
  deliberately last.
- Tests: a hostile-SQL suite (multiple statements, comments, `INTO OUTFILE`, functions that read files, other schemas, CTE tricks) that must all be refused; row-rule tests that the result equals Cube's for the same person.

## Not in this plan
- Building our own login, password storage or SSO. Keycloak federation (LDAP / Google / Microsoft) is documented, not built.
- Multi-tenant hosting (several companies in one install). One company per install.
- Per-user billing, quotas beyond the lab's limits, a mobile app.
- Column-level security beyond what Cube's role rules do today.

## Order, size and what to check by hand
1 (about the size of the designer's phases 1-2), 2, 3, 4, 5a, 5b, 5c. Phases 2 and 3 change stored data: each ships with a migration, a rollback note and a test that a fresh install and an upgraded one end up the same.
After each phase: rebuild the changed images (`auth`, `builder`, the new `admin`, `lab`) and add any new service to `docker-compose.yml`. The default network has an explicit
subnet since #146 (the StarRocks FE and BE have fixed addresses); a new service takes its address from the dynamic range and needs nothing special.

## Open questions (for the product owner)
1. **Do grants only *narrow* what a role allows, or can they also *extend* it?** Narrowing is simpler and safer (a rep never sees profit however shared); extending lets an analyst role be dropped in favour of grants.
   Recommended: narrow only, in phase 2; revisit when someone asks.
2. **Should a user be able to have several roles?** Today one. Several would let "manager" and "inventory" combine without a new role. Recommended: keep one; use groups plus datasets instead.
3. **Deleting a user:** keep their dashboards (ownership moves to the admin or a chosen person) or delete them too? Recommended: the console asks, default is transfer.
4. **Password reset by email:** needs SMTP on the realm. Is an install without SMTP supported? Recommended: yes, the admin sets a temporary password instead.
5. **SQL lab scope:** analysts only (a new role) or any user with a dataset grant? Recommended: a permission on the dataset grant (`lab`), off by default.
6. **Where do SQL-lab queries live?** In the same folders as dashboards (recommended) or a separate tree.
