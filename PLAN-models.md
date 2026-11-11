# Plan: several models in one app, and a real distributor demo

Status: **proposed** (written 2026-11-11). Builds on [`PLAN-decouple.md`](PLAN-decouple.md) (the app knows no model) and [`docs/bring-your-own-model.md`](docs/bring-your-own-model.md). Small phases, one PR each.

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
Today's data is 6,000 random rows. The demo is a **fictional** Turkish FMCG distributor (a made-up name; no real company), generated **inside Postgres** at first start (deterministic, set-based SQL with `generate_series` and hashes, no random(); about 600,000 order lines, a few seconds), so the repo holds code, not data.
- **Time**: January 2023 to the data's "as of" date (a table), calendar with Turkish month and weekday names, ISO week, bayram and Ramazan flags; calendar year (no fiscal year).
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
**1. The services take the model**: builder, lab and admin load every model in `models.yml` and take `model` per request (default: the first, so nothing breaks); saved dashboards and saved queries get `model` (migration SQL, existing rows default); lab routes to the model's Cube SQL port. Tests on both models.
**2. Cube per model and the stack**: `cube-distributor` and `distributor-db` as an additive profile; `MODELS`; nginx writes `STACK.models`; `/dashboards/<model>/`; the standalone overlay kept; CI: a job with both models running (smoke script extended: a query on each Cube, a dashboard list per model, a builder build per model).
**3. The switch in the app**: `STACK.models`, the header select, `?model=` and storage, every page scoped (list, home, builder, lab, admin), a dashboard opens in its own model, locale and currency per model, Turkish strings for the select. Browser tests: switch, each page's lists, a dashboard of the other model opens and switches.
**4. The distributor, realistic**: the generator SQL, the cubes, `access.sql` and the realm's demo people, the six dashboards, the `model.config.yml` vocabulary; a data check (row counts, totals that reconcile, aging buckets that add up, no negative stock) as a test against the generated database; screenshots for the docs.
**5. Docs and the demo script**: README section, `docs/bring-your-own-model.md` ("several models"), a short demo walk-through in Turkish and English (what to click, what it shows).

## Tests and CI
Every phase keeps both models passing the same suites (`dashboards/tests/test_models.py` already loops over `models/*`). New: a two-model browser test on the mock stack (the mock serves both models), the extended smoke script, and the data check of phase 4. The stack job (`distributor-stack`) becomes a **two-model** job (the heaviest CI job: StarRocks stays out of it; AdventureWorks needs its Cube on StarRocks, so the two-model job uses the *test* AdventureWorks setup the other jobs use, or only the Cube-free checks for it: to be decided in phase 2).

## Open questions (with a recommendation)
- **Where the model lives in the address**: `model:` in the spec plus `?model=` for the list pages (recommended), or `/m/<model>/d/<id>` paths. Paths are prettier but touch every link, nginx rule and the public Caddy routing.
- **AdventureWorks under `models/adventureworks/`?** Not needed (`models.yml` points at `cube/`); a move touches Dockerfile contexts, tests, CI and docs for no gain. Recommendation: do not move.
- **A model-level permission** (who may open a model): not now; datasets already decide what a person can read. Add it if empty models in the switch confuse people.
- **The company's name** in the demo: a clearly fictional one (the plan uses "Anadolu Dağıtım"); confirm or pick another.
- **"As of" date**: fixed at the build date of the data (the demo ages, like any dataset) or moving with the clock (a date-shifting view like AdventureWorks' `date_shift_years`). Recommendation: **moving**, a view that shifts the generated history so the latest month is always the current one; the demo then never looks stale.
- **How many dealers and lines**: 220 / 600,000 is a guess at "feels real, loads in seconds". Cube on Postgres without rollups must answer in well under a second at that size; measure in phase 4 and add Postgres indexes or a rollup if not.

## Risks
- Phase 1 touches the saved-dashboard and saved-query stores (migrations on an existing database): ship the SQL as an idempotent `sync-*.sh` step like the others and test it on a database with rows.
- A header switch that reloads the page loses an unsaved draft: warn before switching while a draft has changes (the draft already survives a reload in localStorage, keyed per model after this plan).
- The two-model CI job is slow; keep it to the smoke script, not the full browser suites.

## Estimate
About **2 to 3 weeks**: phases 0-2 are plumbing (about a week), phase 3 the visible part (about 4 days), phase 4 the most work and the most value (about a week: the data and the dashboards, and making them look right).
