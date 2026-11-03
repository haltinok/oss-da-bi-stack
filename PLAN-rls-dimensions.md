# Plan: row-level rules on more than territory

Status: **all three phases done.** Phases 1 and 2 built (2026-11-03, #167); phase 3 built (#168) (2026-11-03): the second dimension is **product category** (`products.category`, instead of channel), `when_empty: deny`, on the sales cubes; starter rules give Managers and Reps every category (postgres/init/09_rls_defaults.sql). Before this plan `territory` was the only dimension, hard-coded in four places; the plan made the dimension a configured thing (`cube/rls_dimensions.json`).

## Where territory is hard-coded now
| Place | What |
|---|---|
| `postgres/init/04_access_schema.sql` | `access.rls_rule.dimension` CHECK (dimension IN ('territory')); primary key already includes `dimension` |
| `auth/main.py` | reads `dimension = 'territory'`, falls back to the dbt seed (`rls.user_regions`), puts `territories` in the Cube token |
| `cube/cube.js` | for any query touching `internet_sales`, `reseller_sales` or `territories`: adds `territories.region equals <list>`; empty list -> 403 "No territories assigned" |
| `admin/main.py`, `admin/access.py`, `admin.js` | one rules tab, values validated against the seed's regions, "territories" wording |

## Design
1. **A dimension registry** (one small file, `access/dimensions.json`, read by auth, admin and cube; kept identical by a test like `access_resolve.py`). Each entry:
   `{id: "territory", label, member: "territories.region", cubes: ["internet_sales","reseller_sales","territories"], values: {source: "cube", member: "territories.region"}, seed: "rls.user_regions" | null, when_empty: "deny" | "allow"}`.
   Adding a dimension = adding an entry (+ its cube member existing in the model).
2. **Database**: drop the CHECK; validate `dimension` against the registry in admin/auth instead (a bad dimension is a 400, never reaches Cube).
3. **Auth**: for every registry dimension read the union of values over the person's rules (user + groups). Token claim becomes `rls: {territory: [...], channel: [...]}` (keep `territories` for the legacy page for one release).
4. **Cube**: for each dimension whose `cubes` the query touches, add `member in values`. Different dimensions are **ANDed**, values inside one dimension are **ORed** (union), as today. `when_empty: deny` keeps today's behaviour for territory (403); `allow` means "no rule = unrestricted" for dimensions where that is the sensible default (say department). The dimension's member must be joinable from every cube it lists (Cube raises a clear error otherwise; a test checks the registry against the model).
5. **Admin console**: the Row rules tab gets a dimension picker (hidden while only one exists); values list comes from the registry's source (Cube `meta`/a distinct query as admin, cached); the preview shows each dimension and where it came from (rules, seed, none). `/rls/rules/...` routes gain `?dimension=` (default `territory`, so the current API and tests keep working).
6. **Lab / builder / dashboards**: no change; they go through Cube. The dashboard filter bar already offers the allowed values since Cube filters them.

## Phases (one PR each, CI-gated)
1. Registry + DB + auth + cube, territory as the only entry (behaviour identical; tests prove it). Includes the registry-vs-model test.
2. Admin console + API for the dimension picker, values source, preview.
3. First extra dimension as proof (needs your choice, below) with a seed/starter rule, docs (`docs/admin.md`, README), and a live RLS test per dimension.

## Risks
- A dimension whose member is not reachable from a fact cube would silently not filter: the registry test must fail the build instead.
- Several dimensions multiply "no access" cases (a person with territory but no channel): the preview must say which dimension is empty.
- Token size grows with values; fine for tens, a note in the docs for thousands (then use a group claim and resolve in Cube).
- Cache keys: rollups are shared across users, so the filter must stay a query filter (as today), never a rollup change.

## Questions for you
1. Which dimension(s) do you want after territory? (sales channel, product category, department/cost centre, something else?) The model needs a member for it.
2. For a new dimension, should "no rule" mean **everything** (allow) or **nothing** (deny, like territory)?
3. Should two rules on the same dimension for different groups be **unioned** (my default) or the **most restrictive** win?
4. Keep the dbt seed fallback only for territory (my default), or allow a seed per dimension?
