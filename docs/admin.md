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
- **Roles:** one of `admin`, `manager`, `rep`, `purchasing`, `marketing` per person, as today. The role decides which data the person may read (see [dashboards.md](dashboards.md#roles-and-security)).

## Row rules
Which sales territories (regions) a person or a group may see, set on the **Row rules** tab. A person sees the **union** of the rules for them and for their groups. With **no rule at all**
the dbt seed (`rls.user_regions`) still decides, exactly as before, so nothing changes until a rule is written. A rule *replaces* the seed for that person: it does not add to it.

- **New rule:** choose a person or a group, tick the territories (the list comes from the seed's regions).
- **What will this person see?** Pick a person and the page shows the territories they will get at their next sign-in, whether the rules or the seed decided, and which rules applied.
- **Follows its owner:** renaming a group renames its rule; deleting a group or a person deletes their rule (a new person with the same username does not inherit it).
- **Where it takes effect:** the auth service reads the rules when it mints the Cube token (15 minutes by default), and Cube applies the territories as before. A change shows at the person's next token.
- **Fails closed:** if the rules database cannot be read, the sign-in fails (503) instead of falling back to the seed, which could give someone more than their rule allows.
- Only the territory dimension exists for now. Inventory roles (`purchasing`, `marketing`) have no territories.

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
