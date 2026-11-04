# The admin console

People, groups and roles, managed from the browser at `/admin/` (the **Admin** link in the dashboard header, shown to admins only). It is a thin screen over Keycloak:
Keycloak stays the place where people, passwords and sessions live, so nothing here replaces its login, and a later LDAP or Google/Microsoft sign-in works the same way.

```
browser ── Keycloak token ──> admin service (admin/) ── its own client-credentials token ──> Keycloak admin API
                               │  only an admin's token gets in; the browser never holds a Keycloak admin token
                               └─ writes one JSON line per change (who, what, to whom)
```

## What an admin can do
- **People:** list (search, filter by role, group and active/inactive), create (a *temporary* password the person must change at their first sign-in), edit name, email, role and groups.
- **Activate / deactivate:** deactivating ends the person's Keycloak sessions and stops new sign-ins. A Cube token already issued to their browser lives out its few minutes (15 by default).
- **Passwords:** *set* one (temporary or permanent), or *reset*: make a temporary password (shown once) or email Keycloak's "update password" link (needs the realm's email settings).
- **Delete:** needs the username typed. Deactivating is what the page suggests: it keeps their dashboards and history.
- **Groups:** create, rename, delete, add and remove people. The people in a deleted group stay.
- **Roles** say what a person may **do** in the app, nothing about data: `admin` can do anything (create, change and delete dashboards, users, groups, datasets and rules, and use the SQL lab); `editor` builds, changes and shares dashboards (and can use the SQL lab when a dataset gives it to them); `viewer` only views: they can open the sample dashboards they can read and the saved dashboards shared with them, and nothing that builds, changes or keeps (no describe/Design/Save, no folders, no SQL lab, no console; the builder service refuses their write calls with 403). What data a person may read comes from their **groups**, the **datasets** and grants below, and the **row rules**: the same for every role except that an admin reads everything.
- **Moving from the old roles** (`manager`, `rep`, `purchasing`, `marketing`): run `postgres/sync-access.sh` (it adds the starter datasets and grants for the groups Managers, Reps, Purchasing and Marketing), then `keycloak/migrate-roles.sh` (each person becomes an `editor` in the matching group), then restart the auth service. The old roles are no longer recognised.

## Row rules
Which rows a person or a group may see, set on the **Row rules** tab: by **territory** (sales regions) and by any other **dimension** listed in the database table `access.rls_dimension`. A person sees the **union** of the rules for them and for their groups. With **no rule at all**
the dbt seed (`rls.user_regions`) still decides, exactly as before, so nothing changes until a rule is written. A rule *replaces* the seed for that person: it does not add to it.

- **New rule:** choose a person or a group, tick the territories (the list comes from the seed's regions).
- **What will this person see?** Pick a person and the page shows the territories they will get at their next sign-in, whether the rules or the seed decided, and which rules applied.
- **Follows its owner:** renaming a group renames its rule; deleting a group or a person deletes their rule (a new person with the same username does not inherit it).
- **Where it takes effect:** the auth service reads the rules when it mints the Cube token (15 minutes by default), and Cube applies the territories as before. A change shows at the person's next token.
- **Fails closed:** if the rules database cannot be read, the sign-in fails (503) instead of falling back to the seed, which could give someone more than their rule allows.
- **Dimensions:** the table `access.rls_dimension` in Postgres lists them (id, the Cube member it filters, the cubes it applies to, where its values come from, and `when_empty`). Today it holds `territory` (`territories.region`) and `product_category` (`products.category`), both on the sales cubes and both `deny` when empty: **a person needs a territory and a product category to see sales data** (admins are exempt). `postgres/sync-access.sh` gives the groups Managers and Reps every category once (the starter rules); anyone else who should see sales (a viewer outside those groups, say) needs a category rule on their person or group. With more than one dimension the tab shows a **Dimension** picker and the table and preview list each one.
- **Read at startup:** Cube, the auth service and this console read the table **once, when they start** (Cube with its own login, `access_cube`, which may read nothing else). A row they could not enforce exactly (an unknown `when_empty`, a member that is not `cube.field`, no cubes, a repeated id) or an empty table stops them from starting, and so does a database they cannot reach within `RLS_REGISTRY_WAIT` seconds (60): they never run on half a list. The tab says where this console's list came from and its version. The auth service puts that version in every Cube token and **Cube refuses a token from a different version**, so restart the three together after a change. Without an access-database login (`CUBE_ACCESS_PG_PASSWORD`, `AUTH_PG_PASSWORD`, `ADMIN_DB_PASSWORD` empty) a service uses the default list, `cube/rls_dimensions.json`, which is also what a new database is seeded with (`postgres/init/10_rls_dimensions.sql`, generated by `scripts/rls_dimensions_sql.py`; the seed only adds missing ids).
- **Adding a dimension:** (1) make the field a dimension of every rollup of the cubes it will filter (`cube/model/cubes/*.yml`), or their queries fall back to the raw tables; (2) add the row, for example
  `INSERT INTO access.rls_dimension (id, position, member, cubes, when_empty, values_source, labels, empty_message) VALUES ('product_subcategory', 30, 'products.subcategory', ARRAY['internet_sales','reseller_sales'], 'allow', '{"kind": "cube"}', '{"en": "Product subcategories"}', 'No product subcategories assigned');`
  (as the `postgres` user: the services' logins cannot change it), plus starter rules if it is `deny`; (3) restart `cube` (and `cube-250m`), `auth` and `admin`: `docker compose restart cube auth admin`. Check each one's log line `rls registry: N dimension(s) from the database (...), version ...`: the three versions must match. The CI test that checks members against the model covers the default file only, so check a new member there yourself: Cube fails a query on a member it cannot join (it denies rather than leaks), but a cube left out of `cubes` is not filtered.
- **How they combine:** inside a dimension a person gets the union of the values from the rules for them and their groups; every dimension that applies to a query narrows it further (AND). `when_empty: deny` (territory) means a person with no value for it gets nothing from those cubes; `allow` means no value, no restriction. The token carries them as `rls: {dimension: [values]}` (the `territories` claim stays for older pages).
- **API:** `PUT|DELETE /rls/rules/{user|group}/{name}?dimension=<id>` (default `territory`); `GET /rls/rules` also returns `dimensions` with their values.
- Only the territory dimension has a dbt-seed fallback. A person with no territory (no rule, not in the seed) gets no sales data: Cube refuses the sales cubes and the territory dimension for them.

## Datasets
A **dataset** is a named set of cubes (for example *Sales facts*: `internet_sales`, `reseller_sales`). On the **Datasets** tab you choose its cubes and **who may use it**: people, groups or roles.

- A cube that is in at least one dataset is **governed**: it can be read only by someone with access to a dataset that holds it. Admins always can.
- A dataset can also hold **single fields** (`cube.field`, for example `internet_sales.gross_profit`): such a field needs a grant even where its cube is open to everybody, which is how profit, supplier data and the like are kept from people who may otherwise use the cube. A grant on a dataset of cubes does not open the fields another dataset holds.
- A cube in **no** dataset is open to everybody. The starter datasets (Sales, Profit and margin, Customers, Inventory, Offers, Supplier and order data) keep the cubes and fields the old data roles kept back; grant them to groups to give access.
- Datasets only open up what they hold: giving someone the Sales dataset does not give them Profit while the Profit dataset is not granted to them, and sales are always limited to their territories.
- A dataset nobody has access to is readable only by admins: the tab says so, so an empty list is never a surprise.
- Tick **Also give the SQL lab** when adding someone to a dataset and they get the [SQL lab](lab.md) (admins always have it). The lab adds no access of its own: what they can read in it is what the dashboards let them read.
- The **preview** on the Row rules tab also lists the cubes datasets keep from a person, and whether they have the SQL lab.

**Where it is enforced.** The auth service puts the cubes and fields a person may not read into the Cube token (`blocked_cubes`, `blocked_members`) and **Cube refuses any query that touches one**, whatever the dashboard says. The builder and the designer leave
those cubes out of the person's catalog, so they are not offered (and a saved dashboard that uses one tells its opener why it cannot open). A grant follows its group's rename and goes with a deleted group or person.
A change shows at the person's next token (15 minutes by default).

## Rules the service keeps (not only the page)
- The **last active admin** cannot be deactivated, deleted or demoted.
- Nobody can deactivate, delete or demote **their own** account.
- Passwords need at least 10 characters.
- Every change is audited: `{"event": "admin", "by": ..., "action": ..., ...}` on the service's stdout. Passwords are never logged.

## Groups in the token
The `dashboard` client has a *group membership* mapper, so a person's groups arrive in their access token (`groups`). The auth service copies them into the Cube token. Nothing uses them yet:
they are what datasets, row-level rules and sharing will point at (see `PLAN-access.md`).

## Setting it up
- A new install gets everything from `keycloak/realm-spike.json` (the `admin-console` client and the group mapper) and `scripts/generate-env.sh` (`ADMIN_CLIENT_SECRET`).
- An existing install: add `ADMIN_CLIENT_SECRET=<random>` to `.env`, run `keycloak/sync-users.sh` (it creates the client, gives its service account only `manage-users`, `view-users`, `query-users`,
  `query-groups` and `view-realm`, and adds the mapper), then `docker compose --profile starrocks up -d --build admin dashboard-cube`.
- Row rules need two Postgres logins on the `access` schema: add `ADMIN_DB_PASSWORD` and `AUTH_PG_PASSWORD` to `.env` (generate-env.sh does for a new install), run `postgres/sync-access.sh` once on an
  existing database (new volumes get the schema from `postgres/init/04_access_schema.sql` and `05_access_users.sh`), then `docker compose --profile starrocks up -d --build admin auth`.
  Without the passwords the tab says rules are off and sign-in works as before.
- Behind Caddy the service is `/admin-api/*`; the page is `/admin/`. The admin console of Keycloak itself stays unreachable from the internet.

## Limits
One role per person. Up to 1,000 people are read at a time (the list shows 200 per request). Group nesting is not used.
