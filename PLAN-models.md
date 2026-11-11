# Plan: several models in one app, and a real distributor demo

Status: **decisions made 2026-11-11, building** (phase 0 in this PR series). Decided: `?model=` (not paths); the demo's dates move with the clock; the company is "Anadolu Dağıtım"; and the demo is **live**: a Faker simulator adds orders, invoices and payments every 15 minutes, like the AdventureWorks one. Builds on [`PLAN-decouple.md`](PLAN-decouple.md) (the app knows no model) and [`docs/bring-your-own-model.md`](docs/bring-your-own-model.md). Small phases, one PR each.

## Goal
One running app serves **more than one model** (today: AdventureWorks on StarRocks, and a realistic **Turkish distributor** on Postgres), and a person **switches between them** from the header. Two things this is *not*:
- It is **not the live / 250M switch**. That switch is the same model on more data, so the same dashboards work on both. Two models have **different dashboards, different builder and lab catalogs, different row rules and a different Cube**. Nothing is shared except sign-in, the people and groups, and the app itself.
- It is **not a cross-model query**. A dashboard, a builder draft or a lab query belongs to one model.

The distributor then becomes a demo worth showing (realistic data, six dashboards, Turkish, row-level rules with demo users), instead of a test fixture ([`models/distributor/README.md`](models/distributor/README.md)).

## What exists, and what that means
| Today | Consequence |
|---|---|
| The browser reads `window.STACK.datasets` (`/cube/config.js`, filled by nginx from env) and picks one by `?dataset=` / localStorage; each has its own Cube URL | The same shape carries models: a list, a choice kept in the URL and the browser, one Cube per entry |
| Dashboards are `/dashboards/<id>.json` and `/dashboards/index.json`, one folder | One folder per model: `/dashboards/<model>/…` |
| builder, lab and admin each load **one** catalog at start (`BUILDER_MODEL_DIR`, `LAB_MODEL_DIR`, `ADMIN_MODEL_DIR`) and one Cube (`CUBE_SQL_HOST`) | They load every model and take the model per request |
| Saved dashboards (`builder.saved_dashboards`) have no model; they are validated against the one catalog | They need a model |
| One access database: datasets and grants (sets of **cube names**), row rules, the row-level registry | Cube names differ between models, so the same tables work for both: no per-model tables |
| `docker-compose.distributor.yml` **replaces** the stack's model | A second, additive Cube service instead (like `cube-250m`), so both models run together |

## The design

### 1. A models file, and a model on every dashboard
`models.yml` at the repo root lists the models the stack serves:
```yaml
models:
  - { id: adventureworks, label: AdventureWorks, root: cube,                  cube: cube,             dashboards: dashboards }
  - { id: distributor,    label: Anadolu Dağıtım, root: models/distributor,   cube: cube-distributor, dashboards: models/distributor/dashboards }
```
`root` is the folder that holds the cube folder and `model.config.yml` (no physical move of AdventureWorks). The first model is the default.
**A dashboard file says which model it is for**: a new optional top-level `model: distributor` in the spec (default: the default model). The validator checks the dashboard against *that* model's catalog; the compiled JSON carries it, so the renderer needs no URL to know which Cube to ask; a saved dashboard stores it (column `model`, existing rows get the default). One field, and every place that today assumes one model (validate, compile, build, saved dashboards, the list pages) has what it needs.

### 2. One Cube per model, side by side
`cube-distributor` next to `cube` (Cube on Postgres; the model folder, `model.config.yml` and `rls_dimensions.json` mounted as `docker-compose.distributor.yml` does now), `distributor-db` for its data. All Cubes share `CUBEJS_API_SECRET`, so **one token works for all** (the auth service mints it once). Profile `distributor` adds the services to the normal stack; `docker-compose.distributor.yml` stays as the **standalone** variant (no StarRocks), which the CI job `distributor-stack` keeps using. `MODELS` (env) says which models a deployment serves; nginx writes them into `STACK.models`.

### 3. The services take the model per request
- **builder**: `GET /catalog`, `/samples`, `/info`, `POST /build`, the saved-dashboard endpoints take `model`; `StandInClient`, validation, `catalog_json` and the examples use that model's catalog and config; samples come from that model's dashboards folder.
- **lab**: `/schema` and `/query` take `model`; the statement goes to *that* model's Cube SQL port (`models.yml: cube`). Saved queries get a `model` column too.
- **admin**: datasets and grants are by cube name, so the console lists the cubes of every model, grouped by model; people, groups and row rules are global. Row rules: the registry holds the dimensions of **both** models (the table `access.rls_dimension` gets the distributor's rows; each Cube enforces only the dimensions whose cubes it serves), so the token's `rls` claim carries both models' values and nothing in auth changes.
- **auth, Keycloak**: unchanged. Demo people for the distributor are added to the realm (section 5).

### 4. The app: one switch, and everything follows it
A **model select in the header** (beside the dataset select, shown only when the stack serves more than one model). The chosen model is in the address (`?model=`, remembered in the browser like `dataset`), and **changing it reloads the page into that model's world**: the dashboards list and tags and search, the start page's recent and shared lists, the builder's catalog and suggestions, the lab's schema and examples, the admin console's datasets tab (filtered by model). A dashboard page needs no `?model=`: the dashboard says its own model (and the header shows it; opening a dashboard of another model switches to it). Each model brings its **own look**: locale, currency (`model.config.yml`), and the page title.
The dataset select (live / 250M) stays inside a model: the distributor has one dataset, so it does not show.
A person who can read no cube of a model (datasets and grants) sees the model with an empty list, as a person with no grants does today; no new permission. (If that turns out to be confusing: a model-level grant later.)

### 5. The distributor as a real demo
Today's data is 6,000 random rows. The demo is a **fictional** Turkish FMCG distributor, **generated by one Python program** (`models/distributor/sim/`, seeded, `faker` with `tr_TR` names) that does two jobs with the same business logic (seasonality, price inflation, dealer sizes, payment terms and lateness, returns), so the history and the live data cannot drift apart:
- **First start (`init`)**: if the database is empty it creates the schema (SQL DDL) and writes the history (about 600,000 order lines, with batched inserts, about a minute) from `today - 3 years` to **now**. The dates **move with the clock**: the history is laid out relative to the day it is generated.
- **Always (`run`)**: a small service, `distributor-sim` (python image, no Airflow), adds new orders (with their lines, invoice and returns) and the payments that fall due **every 15 minutes** (`SIM_INTERVAL_SECONDS`, default 900), plus occasional dealer and price changes. If the stack was down it **catches up** first: it fills the gap since the newest order with the volume the gap would have had, then goes on live. The service has a healthcheck (ready when the history is in), and Cube waits for it.
- The repo holds code, not data (a seeded generator also gives the tests and the screenshots the same numbers).

- **Time**: three years back from the day the data is generated, up to now (the dates move with the clock), calendar with Turkish month and weekday names, ISO week, bayram and Ramazan flags; calendar year (no fiscal year).
- **Dealers (bayi)**: about 220 across the 81 provinces in 7 regions; segments (zincir market, toptancı, bakkal, otel-restoran-kafe); a size curve where a few dealers carry a lot; credit limit and payment term (vade: 30 / 45 / 60 / 90 days); a sales rep each; an opening date (dealers join during the period).
- **Items (ürün)**: about 400 SKUs in 5 categories, subcategories and brands; unit price, cost, case size (koli), VAT rate (1 / 10 / 20 %). Nominal prices rise with inflation through the period (a realistic TRY trend, so a year-on-year comparison means something).
- **Orders**: seasonality (Ramazan, summer beverages, back-to-school stationery), discounts by segment and campaign, order sizes by segment, returns (iade) of 2-3 % of lines.
- **Invoices and payments**: an invoice per order with a due date from the dealer's term; payments land around the due date with a late tail by segment (some partial, some unpaid, a few bounced cheques); payment method mix (havale/EFT, çek, senet, POS, nakit). This gives **open balance, overdue balance and aging buckets** (vadesi geçmemiş, 1-30, 31-60, 61-90, 90+) that move with the data.
- **Stock**: a monthly snapshot per SKU (on hand, reorder point, days of cover): a second kind of fact, like AdventureWorks' inventory.
- **Cubes** (English technical names, Turkish descriptions and labels): `orders`, `invoices`, `payments`, `returns`, `stock`, and the dimensions `dealers`, `items`, `calendar` (+ the due-date role), `reps`. `meta:` as in the bring-your-own-model page (`kind`, `primary`, `format`, `sort_by`).
- **Row-level rules**: `dealer_region` (as now) and `sales_rep` (a rep sees their own dealers). Demo people in the realm (`marmara_mudur`, `ege_temsilci`, `finans`, …) with rules and datasets in `access.sql`, so the admin console and the row rules show something real.
- **Six dashboards** (Turkish, hand-written YAML; tabs where it helps): *Satış özeti* (key figures with the year comparison, monthly trend, region, category, top dealers), *Bayi performansı* (pivot dealer × month, ABC, segment), *Ürün ve kategori* (treemap, brand, margin), *Tahsilat ve vade* (aging, overdue by dealer, payment methods), *Stok durumu* (the snapshot), *İade analizi*.
- The generic stand-in composes from these cubes (revenue, dealers, categories, time); the snapshot dashboard is written by hand (the generic composer has no snapshot kind: a known gap).

## Phases
**0. The models file and the `model` field (small)**: `models.yml`, a loader in dashspec (`models.load()`), the optional `model:` in the spec (schema, validator picks the catalog, compiler carries it), `dashspec build` writes `build/<model>/`, `index.json` per model. Tests: both models' dashboards build into their folders; a dashboard naming an unknown model is refused. No behaviour change for one model.
**1. The services take the model (built)**: builder, lab and admin load every model in `models.yml` and take `model` per request (default: the first, so nothing breaks); saved dashboards and saved queries get `model` (migration SQL, existing rows default); lab routes to the model's Cube SQL port. Tests on both models.
**2. Cube per model and the stack (built)**: `cube-distributor` and `distributor-db` as an additive profile; `MODELS`; nginx writes `STACK.models`; `/dashboards/<model>/`; the standalone overlay kept; CI: a job with both models running (smoke script extended: a query on each Cube, a dashboard list per model, a builder build per model).
**3. The switch in the app (built)**: `STACK.models`, the header select, `?model=` and storage, every page scoped (list, home, builder, lab, admin), a dashboard opens in its own model, locale and currency per model, Turkish strings for the select. Browser tests: switch, each page's lists, a dashboard of the other model opens and switches.
**4. The distributor, realistic (built)**: the generator and simulator (Python, above), the cubes, `access.sql` and the realm's demo people, the six dashboards, the `model.config.yml` vocabulary; a data check (row counts, totals that reconcile, aging buckets that add up, no negative stock, the catch-up fills a gap) as a test against the generated database; screenshots for the docs.
**5. Docs and the demo script (built)**: README section, `docs/bring-your-own-model.md` ("several models"), a short demo walk-through in Turkish and English (what to click, what it shows).

## Tests and CI
Every phase keeps both models passing the same suites (`dashboards/tests/test_models.py` already loops over `models/*`). New: a two-model browser test on the mock stack (the mock serves both models), the extended smoke script, and the data check of phase 4. The stack job (`distributor-stack`) becomes a **two-model** job (the heaviest CI job: StarRocks stays out of it; AdventureWorks needs its Cube on StarRocks, so the two-model job uses the *test* AdventureWorks setup the other jobs use, or only the Cube-free checks for it: to be decided in phase 2).

## Open questions (with a recommendation)
- **AdventureWorks under `models/adventureworks/`?** Not needed (`models.yml` points at `cube/`); a move touches Dockerfile contexts, tests, CI and docs for no gain. Recommendation: do not move.
- **A model-level permission** (who may open a model): not now; datasets already decide what a person can read. Add it if empty models in the switch confuse people.
- **How many dealers and lines**: 220 / 600,000 is a guess at "feels real, loads in seconds". Cube on Postgres without rollups must answer in well under a second at that size; measure in phase 4 and add Postgres indexes or a rollup if not.

## Risks
- Phase 1 touches the saved-dashboard and saved-query stores (migrations on an existing database): ship the SQL as an idempotent `sync-*.sh` step like the others and test it on a database with rows.
- A header switch that reloads the page loses an unsaved draft: warn before switching while a draft has changes (the draft already survives a reload in localStorage, keyed per model after this plan).
- The two-model CI job is slow; keep it to the smoke script, not the full browser suites.

## Estimate
About **2 to 3 weeks**: phases 0-2 are plumbing (about a week), phase 3 the visible part (about 4 days), phase 4 the most work and the most value (about a week: the data and the dashboards, and making them look right).

## Phase 1 as built
- `dashspec.models.served()` narrows models.yml to `$MODELS`. **builder**: loads a catalog per model (`BUILDER_MODEL_DIR` still names a single model for an older setup); `/info`, `/catalog`, `/samples`, `/saved` (filter) take `?model=`, `POST /build` takes `model`, and a build for a non-default model comes back with `model: <id>` in its YAML; saved dashboards are validated against the catalog of the `model:` their YAML names (`core.Catalogs` stands in where a catalog was passed); `/info` lists the models. No new column: the model is the YAML's, read and cached like the tags.
- **lab**: `/schema`, `/query`, `/export` and the saved-query endpoints take `model`; a statement goes to that model's Cube SQL host (models.yml `cube`); `lab.saved_queries` gets a `model` column (06_lab_schema.sql, idempotent, run by sync-lab.sh), empty meaning the default.
- **admin**: the datasets screen's cube list covers every model, each cube tagged with its model.

## Phase 2 as built
- `docker-compose.yml`: `distributor-db` and `cube-distributor` under the profile `distributor` (additive: with `starrocks` both models run side by side); Keycloak, auth, Cube Store, the pages, builder, lab and admin are also in that profile; the three catalog services get `MODELS` and `models.yml` + the model folders mounted at `/srv/models` (their images lost the baked single-model env vars and fall back to the baked model when the mount is absent); `dashboard-cube` gets `MODELS`, `MODEL_LABELS`, `CUBE_PORTS` and each model's compiled dashboards at `/dashboards/<model>/…` (the old `/dashboards/<id>.json` stays the default model's); `/cube/config.js` gains `STACK.models` (the default's Cube is still `STACK.cube`); Caddy routes `/cubejs-distributor/*`.
- The stack's one registry, `cube/rls_dimensions.json`, now lists every model's row-level dimensions (the distributor's `dealer_region` too; a test keeps each model's own file identical to its entry); the admin console shows only the dimensions of the models it serves.
- `docker-compose.distributor.yml` shrank to the standalone case (the distributor as the only model). `scripts/distributor-smoke.sh` and the CI job use `cube-distributor` and check `STACK.models`, `/dashboards/<model>/` and the builder and lab per model.
- Not run here: both models in one stack together (StarRocks is the heavy part): its pieces are covered by `docker compose config`, `scripts/check-config-js.sh` (the models array for one and two models, local and public) and the standalone smoke test.

## Phase 3 as built
- `lib/model.js`: the model a page is in (`?model=`, else a hint such as the draft's, else the last one used, else the first), the header select, and the address of the same page in another model (a dashboard page goes to the list; the dataset is dropped). A one-model stack (or an older one with no `STACK.models`) is unchanged: no switch, no parameters.
- The renderer picks its model before it creates the Cube client: the default model keeps the stack's datasets (live / 250M), another model has its own Cube and one dataset; the list, the dashboard files (`/dashboards/<model>/`) and the builder calls are the model's; **a dashboard that says another model (`model:` in a saved or compiled one, or a file found only in the other model's folder) opens the page in that model.** The builder API sends `model` (info, catalog, samples, saved list, build); the start page, the lab (schema, query, export, saved queries) and the admin console (the dataset cube list shows each cube's model) follow.
- Not done on purpose: a draft is still one slot per browser (it says its own model, and `/d/draft` opens in it), no warning when switching with unsaved changes (the draft survives a reload), no model-level permission.
- Tests: `model.test.mjs` (the picking rules, the addresses, the switch), `models.py` (two models on the mock stack: the switch, lists, a dashboard drawn from the other model's Cube, links that switch the page, the builder, the start page, the lab, a one-model stack with no switch) in CI; the mock stack serves both models.

## Phase 4 as built
- `models/distributor/sim/` (`distributor_sim`: `reference` the calendar, regions, segments and about 87 products / 370 items; `engine` the orders, invoices, payments and returns; `db`; `main` with `init`, `once`, `run`). Three years of history in one transaction (about 45 s: 600k lines, 130k orders, 133k payments, 15k returns), then a tick every `SIM_INTERVAL_SECONDS` with catch-up. The plan table holds payments and returns that are not yet due and moves them into the facts when they are. `distributor-sim` is a compose service (healthcheck: the history is in); `cube-distributor` waits for it.
- Cubes: `orders`, `invoices` (status, aging bucket, overdue balance), `payments`, `returns`, `stock` (the newest snapshot) and `stock_history`, `dealers`, `reps`, `items`, `calendar`, `maturity_dates`. Six dashboards (Satış özeti, Bayi performansı, Ürün ve kategori, Tahsilat ve vade, Stok durumu, İade analizi) and a vocabulary of Turkish words for the stand-in.
- Row rules: `dealer_region` and `sales_rep` in the one registry; the realm has `marmara_mudur`, `marmara_temsilci` and `ege_temsilci` (groups `RegionManagers`, `FieldReps`); `models/distributor/rules.sql` gives them their rules on a standalone stack.
- Tests: the engine without a database (`models/distributor/sim/tests`, in the dashspec CI job), and `scripts/distributor-smoke.sh` against the live stack (CI job `distributor-stack`).
- Left out: the pivot, ABC and treemap panels the plan imagined (the panel types do not exist yet; the dashboards use bars, pies, tables and time charts), a `finans` user, tabs in the dashboards, a data-reconciliation test against the generated database (checked by hand: invoice = lines + VAT, aging adds up, no negative stock), screenshots.

## Phase 5 as built
`docs/demo-distributor.md` (start, a walk-through in English and Turkish, what the data does), the "several models" section of `docs/bring-your-own-model.md`, the README link, and the distributor's own README brought up to date.
