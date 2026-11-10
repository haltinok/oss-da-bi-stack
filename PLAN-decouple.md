# Plan: the app knows no model

Status: **all six phases built and merged** (#196 to #201, 2026-11-10); what is left is under "Left over" at the end (written 2026-11-10, reviewed against the code the same day: the table below, the rule, phases 0, 1, 3, 4 and 5 and the estimate carry the review's corrections). Six phases, one PR each, like [`PLAN-slicer-fields.md`](PLAN-slicer-fields.md). Phase 0 ships first: it is the test every later phase is checked against.

## Goal
The dashboard app (renderer, designer, builder, dashspec, lab, admin, auth) runs on **any Cube model**, not only the AdventureWorks one. Everything it knows about the data comes from Cube's `/v1/meta` (with each member's `meta:`) or from a small config file that the model ships. **No cube or member name appears in the app's code.**

This is the step that turns the repo from "a demo with a good app in it" into "a product with a demo next to it". It is also what the PostgreSQL route needs. A second warehouse is only a second model and profile, if the app does not care which model it reads.

## The rule (goes into CLAUDE.md)
> The app knows no model. Cube names, member names, channels, fiscal months and example queries come from `/v1/meta`, the model's `meta:`, or `model.config.yml`, never from code. Example dashboards, the Cube model, dbt, Airflow and tests may name members; nothing under `dashboard/`, `builder/`, `dashboards/dashspec/`, `lab/`, `admin/`, `auth/` or `cube/cube.js` may.
> `agent/` and `actions/` (the inventory proposal agent and the write-back actions) are **model add-ons**: they belong to one model by nature, live beside it, and are exempt from the guard. Which cubes the agent may read is `agent.cubes` in `model.config.yml`.

## Where the coupling is today
Read from the code on 2026-11-10:

| Where | What | Size |
|---|---|---|
| `builder/composer.py` | `compose_sales` / `compose_inventory`, `channels()` returning `internet_sales` / `reseller_sales`, the `internet` / `reseller` labels and colours, measure names (`revenue`, `gross_profit`, `orders`, `units`) | ~36 references, the largest piece |
| `dashboard/static/app.js` | the original hand-built AdventureWorks live dashboard: `CHANNELS = ["Internet", "Reseller"]`, order `STATUS` codes, a July fiscal year in `fyOf` / `fyRange`; still served from `index.html` and patched in by `nginx.conf.template` | 1,246 lines |
| `dashboards/dashspec/semantic.py` | `FACTS = ("internet_sales", "reseller_sales")`; the generated guide's prose names the AdventureWorks cubes | small |
| `dashboards/schema/dashboard.schema.json`, `dashspec/docs.py` | theme tokens `internet` and `reseller`; `bar.stack` is documented as internet + reseller | small |
| `dashboard/static/lib/compare.js` | `YEAR_FIELDS = ["fiscal_year", "calendar_year"]`: the comparison finds the year by the **member's name ending**. (`render/plan.js` only uses `fiscal_year` / `calendar_year` as bucket *kinds*, not member names: no change.) | small, but subtle |
| `dashboard/cube/cube-source.mjs` (+ `boot.js`, `cube/config.js`) | `app.js`'s data adapter: `CH = { Internet: "internet_sales", Reseller: "reseller_sales" }` and the `noProfit` / `reorder` / `overstock` flags by cube name. **The most coupled file (48 hits).** Goes with `app.js` | medium |
| `builder/core.py` | `example_spec()` builds the examples **in the LLM prompt** by running the rule-based composer on three fixed sales and inventory requests. On another model the composer finds nothing and the prompt has no example, which is what lets a cheap model write valid files. `EXAMPLES` (the builder page's suggestions, EN and TR) are sales and inventory prompts too | medium, and it breaks "the LLM path needs no change" |
| `dashboard/static/lib/designer-structure.js` | `PREFERRED_MEASURES` (`revenue`, `orders`, ...): which measure a new panel starts with is picked by **measure name**. Found by the phase 0 guard; it is what `meta.primary` replaces (phase 1) | small |
| `cube/cube.js` | `AGENT_CUBES` (line 44) and the agent's model files (line 203) name cubes; the `territory` fallback reads the old `territories` token claim (line 172). This is app logic, not model | small |
| `auth/`, `admin/`, `dashboard/cube/cube-client.mjs` | the token claim `territories`, the dbt seed `mart.dim_user_territory`, `/rls/rules` answering `regions`, an error example naming `internet_sales.gross_profit` | small, spread over files |
| `dashboard/static/render/lab.js`, `lab-strings.js` | the SQL lab's example queries and placeholder (`from internet_sales cross join products`) | small |
| `dashboard/static/render/strings.js` | the calculation hint's example (`sum(internet_sales.revenue, reseller_sales.revenue)`), EN and TR | small |
| `cube/rls_dimensions.json` | already a registry (good). But `values.kind: seed_regions` reads the dbt seed, and auth/ and admin/ keep copies | small |
| `dashboards/dashspec/validate.py`, `dashboards/README.md` | `denied()` is already a no-op (roles are capabilities since #166), but the stub and the README's paragraph on rep/purchasing/marketing rules remain | cleanup |

Not counted: `lib/synonyms.js` (generic search words such as "product" and "territory"), the doc comments in `render/plan.js` that use `internet_sales.order_number` and `dates.fiscal_year` as examples (reword them, no logic), and the ordinary words `dates`, `products`, `customers` in comments. A bare-word grep finds about 300 hits in the app folders and is mostly noise (see the guard in phase 0).

Not coupled already: `catalog.py` reads `/v1/meta` (`from_cube`) or the model files (`from_model`), with `sort_by` and `label_prefix` from `meta:`. The spec's `time: { dimension, fiscal_year_start }` is already per file. Datasets, grants and row rules are data, not code.

## The design

### 1. Cube's metadata is the catalog
Everything the app needs per cube and member goes into the model's `meta:` and arrives through `/v1/meta`. `catalog.py` keeps reading both sources the same way.

```yaml
cubes:
  - name: internet_sales
    meta:
      kind: fact                 # fact | dimension (replaces FACTS)
      series: Internet           # the label when facts are shown side by side (replaces the internet/reseller labels)
      color: series1             # default theme token for this fact's series
    measures:
      - name: revenue
        meta: { format: money, primary: true }   # what a KPI row or chart picks first
```

### 2. A model ships a small `model.config.yml`
This covers what is not about one cube:

```yaml
time:
  dimension: dates.full_date
  fiscal_year_start: 7            # the default for new dashboards; a file can still override it
  year_fields: { fiscal: dates.fiscal_year, calendar: dates.calendar_year }
lab:
  examples:                       # shown in the SQL lab, per language
    - { title: { en: Revenue by category, tr: Kategoriye göre ciro }, sql: "select category, measure(revenue) ..." }
builder:
  vocabulary: builder/vocabulary.yml   # optional: synonyms for the rule-based stand-in
```

The app reads it once at start-up, beside `/v1/meta`. A model without it still works: no fiscal year, no lab examples, a stand-in that only knows the members' own names.

### 3. Generic theme tokens
`series1 … series8` plus the existing `focus`, `live`, `good`, `bad`, `warn`. `internet` and `reseller` stay as **deprecated aliases** of `series1` and `series2` for one release. The validator accepts them with a lint warning, and the designer writes the new names.

## Phases

### Phase 0: the guard rail (1 day)
- A second, small model under `models/<name>/` (`cube/`, `dbt/`, `dashboards/`, `model.config.yml`, `vocabulary.yml`; AdventureWorks moves there in phase 5), deliberately not AdventureWorks. **Proposed subject: a Turkish SME distributor** (`bayi`, `stok`, `tahsilat`): it is not the same shape, it exercises the Turkish vocabulary, and it is a demo for the local market. Give it **no "channel" concept** so the series logic is tested. It has two facts, one role-playing date and one text dimension with `sort_by`. It runs on **Postgres**, which also starts the Postgres route.
- Seed data as a dbt seed or a SQL init file: a few thousand rows, no simulator.
- Three or four example dashboards for it, in YAML.
- The `dashspec` tests, the builder tests and `pages_gallery.py` run against **both** models (pytest parametrised on the catalog).
- A CI job `no-model-names` runs a grep over the app folders (the ones in the rule, not the add-ons) for **qualified members** (`\b<cube>\.[a-z_]+\b`) and **quoted cube names** (`["']<cube>["']`) of either model, never bare words (`dates`, `products` are ordinary words). Justified hits go in an allow-list file with a reason each. It **starts as a warning** that lists the hits, and becomes an error in phase 5.
- The rule above goes into CLAUDE.md.

### Phase 1: metadata, not constants (2–3 days)
- `meta.kind`, `meta.series`, `meta.color`, `meta.format`, `meta.primary` go into both models. `catalog.py` reads them from both sources.
- Delete `FACTS`. `semantic.py`'s generated guide describes "a fact" and "a dimension" generically and takes its examples from the catalog it is given.
- Update the role paragraph in `dashboards/README.md` to match #166. **Keep the `denied()` stub for now**: it has nine call sites in `builder/composer.py` (plus the import in `core.py`), so it is deleted in phase 4 when the composer is rewritten anyway.

### Phase 2: theme tokens and time (1–2 days)
- `series1…8` in the schema, the themes CSS and the renderer. `internet` / `reseller` become aliases with a lint warning. Rewrite the example dashboards with the new names.
- `compare.js` and `plan.js` find the fiscal and calendar year fields from `model.config.yml` (`time.year_fields`), not by name ending. When none are configured, a comparison moves only date ranges (a year filter is not a year to it). **Built differently from the first draft:** the validator does not refuse `compare` (a date-range comparison needs no year field); the config sits beside the model's cube folder (`<model>/model.config.yml`, so `cube/model.config.yml` for AdventureWorks, which Cube must not see inside its model folder), is read by `catalog.from_model` and compiled into the spec as `yearFields` (with the roles of the calendar), and the three Docker images that read the model get it through a `modelconfig` build context.
- The calculation hint and the `bar.stack` docs take their examples from the catalog (the first two facts that share a measure name) or use neutral placeholders (`a.revenue`, `b.revenue`).

### Phase 3: the SQL lab and the row rules (1 day)
**Built** in three parts: the lab examples (`lab.examples` in model.config.yml, each listing the cubes it reads so it is only offered to someone who can read them; none configured: examples made from the catalog), the agent's cubes (`agent.cubes` and `datasets.overlay_cubes` in model.config.yml, read by `cube/cube.js`), and **one** registry file (`cube/rls_dimensions.json`: the auth and admin images copy it from the `modelconfig` build context, the copies are gone and a test checks it). **Not built, on purpose:** the token carrying only `rls` and `seed_regions` becoming `cube`: the territory dimension still reads the dbt seed (`seed: true`), so changing it would silently drop the access of people who are only in the seed. That needs a migration of the seed into rules first; it is its own piece of work.

- Lab examples and the placeholder come from `model.config.yml`. With none, the lab shows one example built from the catalog (the first fact, its primary measure, its first joined dimension).
- `rls_dimensions.json` moves next to the model (`cube/model/` or the model's folder). `values.kind: seed_regions` becomes `kind: cube` (distinct values of the member) or `kind: list`. auth/ and admin/ read the one file instead of keeping copies; the copy-check test goes.
- **The token carries only `rls: { dimension: values }`.** The `territories` claim, the `territory` fallback in `cube/cube.js` and in `cube-client.mjs`, the dbt seed `mart.dim_user_territory` as a special source and `/rls/rules` answering `regions` all go: territory is one row-level dimension among others. The agent's cube list (`AGENT_CUBES`, and the model files `cube.js` loads for it) moves to `agent.cubes` in `model.config.yml`.

### Phase 4: the builder's stand-in (3–5 days, the largest)
**Built differently from the first draft** (the stand-in's AdventureWorks logic is a hand-made dashboard recipe, which is model-specific by nature, so it became an **add-on** like agent/ and actions/, not a vocabulary file): `builder/composer.py` is now the shared helpers (words, the result, the page layout) and a dispatcher; a model that names a recipe (`builder.recipe` in its model.config.yml) is composed by `builder/recipes/<name>.py` (AdventureWorks: the old composer, moved, unchanged, all its tests pass); every other model by `builder/generic.py`, which reads only the catalog (the fact cubes, each cube's first measure, the members' own names, joins, the time field, the year fields) and the model's optional `vocabulary` (`words`: a word to a member, `labels`: the names a Turkish page shows). The prompt's example specs and the page's suggestions come from the recipe or, for a model without one, from the catalog (`builder.examples` in the config wins). `visible_catalog` no longer drops the model's meta. The guard skips `builder/recipes/`. Not done: the generic composer does not edit an existing dashboard (it says so), has no inventory-style (snapshot) dashboard, and `denied()` stays for the recipe. `builder/evals.md` with a real key on both models still needs someone with a key.

- Split `composer.py` into a **generic composer** and a **vocabulary**:
  - the generic composer knows panel types, measures, dimensions, time, top N, slicers and comparisons, and gets everything else from the catalog: facts from `meta.kind`, the first measure from `meta.primary`, series labels and colours from `meta.series` / `meta.color`;
  - `vocabulary.yml` (per model, optional) maps words in English and Turkish to members and to fact groups: e.g. `ciro, revenue, sales → *.revenue`, `bayi, reseller → reseller_sales`, `stok, inventory → inventory_health`.
- `compose_sales` and `compose_inventory` become one `compose` over facts. An inventory-style fact (a snapshot, no comparison) is marked in the model as `meta: { snapshot: true }`.
- Today's English and Turkish test prompts keep passing on AdventureWorks (that vocabulary file holds what the code knew). A smaller set of prompts runs on the second model.
- **The LLM path does change.** `core.example_spec()` builds the prompt's example specs by composing fixed sales and inventory requests; on another model it would give none. It must build its examples from the generic composer over the catalog's own facts (the first fact and its primary measure, a time chart, a breakdown, a table), and `EXAMPLES` (the builder page's suggestions) move to `builder.examples` in `model.config.yml`, with a catalog-built suggestion when absent. Add a test on the second model that the prompt carries at least one valid example.
- Delete the `denied()` stub with its nine call sites (kept in phase 1).
- Run `builder/evals.md` with a real key on **both** models as part of this phase (it has never run against a real API).

### Phase 5: retire `app.js`, close the gate (1–2 days)
**Built differently from the first draft** (the docs page is [bring-your-own-model.md](docs/bring-your-own-model.md)): `app.js`, `index.html`, its Cube adapter (`cube-source.mjs`, `boot.js`) and the `sub_filter` that patched them in are **deleted** (git history keeps them), and `/` redirects to the start page. `dashboards/sales-overview.yml` already covers the old page (KPIs with a year comparison, a channel trend, territory and product bars, the latest orders), so no new `live-sales.yml` was written. The tests of the old page went with it: `render.py`, `header.py`, `dataset.py` and the per-role `e2e.py` (the renderer's own suites cover the dataset switch and the panels; **the per-role live-stack browser test and the header-width test are not replaced**: they would need porting to `/d/`), and renderer.py's parity check against the old page. The guard is an **error** in CI (`--strict`), with zero hits, and a test checks it finds a planted name.

## Added after the six phases
- **The second model runs on a real stack**: `docker-compose.distributor.yml` (Postgres data, Cube on Postgres, the same Keycloak, auth, dashboard pages, builder, lab and admin console), `scripts/distributor-smoke.sh` and the CI job `distributor-stack`. It found a bug in phase 4 (the builder page's suggestions were still AdventureWorks'), fixed with it. The overlay seeds the access database per model (`models/distributor/access.sql`).

## The territory migration (done after the six phases)
The dbt seed no longer decides anyone's territories: `postgres/init/12_territory_rules.sql` moved the demo's seed into rules once (preserving each person's effective access) and made the territory dimension a registry `list`; the auth service no longer reads StarRocks (no `territories_for`, no pymysql, no `AUTH_DB_*`), the token carries only `rls`, `cube.js` has no `territories` fallback, the admin console has no seed (no `regions`, no "from the seed" preview), and the dbt seed + `rls.user_regions` model, the `auth_ro` StarRocks login and its grants are gone. An existing install runs `postgres/sync-access.sh` (and its own users need rules first: docs/admin.md, *Moving the dbt seed into rules*). A legacy `seed_regions` / `seed` registry row is still accepted and ignored.

## Left over
- The generic composer has no inventory-style (snapshot) dashboard and does not edit an existing one; `denied()` stays for the recipe; `builder/evals.md` with a real key on both models.
- The per-role live-stack browser test and a header-width test for the renderer's pages.

- Rebuild the live AdventureWorks dashboard as a YAML dashboard (`dashboards/live-sales.yml`): KPIs, trend, channel split and latest orders, with the polling the renderer already has (`live` theme token). Order status labels go in the Cube model (a `case` dimension) or the dbt mart, not in JS.
- Move `app.js` to `examples/legacy-app/` or delete it **together with its data adapter** (`dashboard/cube/cube-source.mjs`, `boot.js`, `cube/config.js` and the script tags in `index.html`). Remove the `sub_filter` block in `nginx.conf.template`, and make `index.html` the start page (`/home/`) or the dashboards list.
- Move AdventureWorks to `models/adventureworks/` so both models sit in the same layout.
- The `no-model-names` CI job becomes an **error**.

## Definition of done
- `no-model-names` passes with zero hits (apart from the allow-list) in `dashboard/`, `builder/`, `dashboards/dashspec/`, `lab/`, `admin/`, `auth/` and `cube/cube.js`.
- The full test suite and the screenshot gallery pass on **both** models.
- Starting the stack with the second model only (`--profile postgres`, its own `CUBEJS_DB_TYPE=postgres`) gives a working start page, dashboards, designer, builder (stand-in and LLM), SQL lab and admin console, with no AdventureWorks name on any screen.
- `docs/` has a page "Bring your own model": the `meta:` keys, `model.config.yml`, `vocabulary.yml`, and what happens when each is missing.

## Decisions to confirm (each has a proposal)
- **Second model's subject: a Turkish SME distributor** (`bayi`, `stok`, `tahsilat`), with no channel concept. A non-sales shape tests the decoupling harder, and it doubles as a demo for the local market (and for SMEs, the product's audience). Alternatives: a clinic or HR.
- **Where a model lives: `models/<name>/{cube,dbt,dashboards,model.config.yml,vocabulary.yml}`**, introduced in phase 0 for the second model only; AdventureWorks moves there in phase 5. That avoids a big move up front while the target layout is the one a customer install uses.
- **Alias lifetime** for `internet` / `reseller`: until a migration script has rewritten the saved dashboards in the store (`builder.saved_versions`, not in git), not "one release".
- **Vocabulary depth: light.** `vocabulary.yml` maps words to members and fact groups; layout habits ("a sales dashboard starts with KPIs and a trend") stay generic in the composer.

## Estimate
About **3 weeks** of focused work (the first draft said 2 to 3). Phase 4 grew with the LLM prompt's examples and the builder page's suggestions; phase 5 grew with `cube-source.mjs`. Phase 4 still carries the most risk and phase 0 the most value. The rest is mostly mechanical once phase 0's tests are in place.
