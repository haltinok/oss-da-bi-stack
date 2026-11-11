# Bring your own model

The app (the renderer, the designer, the builder, dashspec, the SQL lab, the admin console and the auth service) **knows no model**: every cube, member, series label, example query and year field it uses comes from Cube's `/v1/meta`, the model's `meta:` keys or one small file, `model.config.yml`. AdventureWorks (`cube/model/`) and the distributor example (`models/distributor/`) are two such models; the tests run on both, and `scripts/no_model_names.py` (CI job `no-model-names`) fails the build when the app's code names a cube or member of either.

A model is a folder with a `cube/` folder of Cube files (what Cube loads) and, **beside it**, `model.config.yml` (Cube must not see it inside its own folder). For AdventureWorks the folder is `cube/` itself (`cube/model/` is the cube folder). `models/distributor/` is the template: `cube/cubes/*.yml`, `postgres/10_init.sql` (seed data) and `postgres/20_cube_user.sh` (a read-only login for Cube), `dashboards/*.yml`, `model.config.yml`, `README.md`.

## `meta:` in the Cube files
Read from the files by `dashspec` and from `/v1/meta` by a running Cube; both give the same catalog.

| Where | Key | Meaning | When it is missing |
|---|---|---|---|
| cube | `kind: fact` | an events cube (the rest are dimensions) | no fact cubes: the builder's stand-in has nothing to build from |
| cube | `series: Internet`, `color: series1` | how a fact is named and coloured when facts are shown side by side | the chart's own palette, the measure's name |
| cube | `label_prefix: Ship` | the role of a role-playing cube (`extends` the calendar): "Ship month name" | the plain field name |
| measure | `format: money \| int \| pct \| decimal \| number` | how a measure is shown | `number` |
| measure | `primary: true` (or a rank: `1`, `2`, ...) | the measure a new panel starts with, first | the cube's first measure |
| dimension | `sort_by: month_of_year` | a text field that sorts by another field of its cube (months January to December) | alphabetical |

## `model.config.yml`
Every key is optional. Read once, at start-up, by dashspec (so by the builder, the lab and the admin console: their images get the file through the `modelconfig` build context) and, for the agent's cubes, by `cube/cube.js`.

```yaml
time:
  dimension: calendar.full_date                 # the default time field of a new dashboard
  fiscal_year_start: 7
  year_fields: { fiscal: dates.fiscal_year, calendar: dates.calendar_year }   # what "compare with the previous year" moves
locale: tr-TR                                   # the default of a dashboard the stand-in builds
currency: TRY
lab:
  examples:                                     # the SQL lab's examples; each lists the cubes it reads
    - { title: { en: Revenue by category, tr: Kategoriye göre ciro }, cubes: [sales, items], sql: "select ..." }
builder:
  recipe: adventureworks                        # a hand-made rule-based recipe (builder/recipes/<name>.py, a model add-on); none: the generic composer
  examples: { en: ["Revenue by month"], tr: ["Aylık ciro"] }     # the requests the builder page offers
vocabulary:                                     # what the generic stand-in understands beyond the members' own names
  words: { ciro: orders.revenue, bolge: dealers.region }        # a word without accents -> a member
  labels: { orders.revenue: Ciro }                              # the names a Turkish page shows
agent:
  cubes: [stock]                                # the cubes the proposal agent (a service account) may read, and nothing else
datasets:
  overlay_cubes: [stock]                        # cubes of this model a dataset adds to the model it is built from
```

| Key | When it is missing |
|---|---|
| `time.year_fields` | a comparison moves only date ranges (a year filter is not a year to it) |
| `lab.examples` | the lab offers up to three made from the catalog (a fact's first measure by a text field of each cube it joins to) |
| `builder.recipe` | the generic composer: it understands the members' own names ("orders by region"), builds a key-figures row, a time chart, a bar or pie per field and a table, and does not edit an existing dashboard |
| `builder.examples` | suggestions made from the catalog |
| `vocabulary` | only the members' own names are understood |
| `agent.cubes` | an agent token reads nothing |
| the whole file | everything above, and no fiscal year |

## Row-level security
The row rules (`rls_dimensions.json`, beside the cube folder: one file that Cube, the auth service and the admin console all read; the images copy it at build time) name the dimension, its member and the cubes it limits. They are data of the model, not of the app.

## Running a model
A model is added to the stack as its own Cube service (see `cube-distributor` in `docker-compose.yml`: Cube's `CUBEJS_DB_TYPE` and login for the model's database, its folder mounted over Cube's model folder and its `model.config.yml` beside `cube.js`), its entry in `models.yml`, its dashboards' build folder mounted for nginx (`/dashboards/<model>/…`), and its port and label in `CUBE_PORTS` / `MODEL_LABELS` of `dashboard-cube` (the header switch and the browser's `STACK.models`); `MODELS` says which models a stack serves, and the builder, lab and admin console read `models.yml` (mounted at `/srv/models`). The row-level dimensions of every model are in the one registry, `cube/rls_dimensions.json`, so Cube, auth and the console enforce one list. `docker-compose.distributor.yml` is the overlay for a stack whose only model is the distributor. The access database is seeded per model (`<model>/access.sql`, generated from `<model>/rls_dimensions.json`). [`models/distributor/README.md`](../models/distributor/README.md) has the commands.

## Several models
`models.yml` (repo root) lists the models a stack serves: `id`, `label`, the Cube model folder (`dir`), the folder of its dashboards and its Cube's compose service. The first is the default. A dashboard says which model it is for with a top-level `model: <id>` (none: the default model); `dashspec validate` checks it against that model's cubes, `dashspec build` writes each model's dashboards into its own `build/` folder, and the compiled file carries the model. Two models share nothing but sign-in and the people: different dashboards, catalogs, row rules and Cube.

## Checking a model
```bash
scripts/dashspec validate --model models/<name>/cube models/<name>/dashboards/*.yml
PYTHONPATH=dashboards python -m pytest dashboards/tests/test_models.py        # picks up every models/<name>/cube
python scripts/no_model_names.py --strict                                       # the app names no model
```
