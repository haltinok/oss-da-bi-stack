# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Rules for working in this repo

## The app knows no model
Cube names, member names, channels, fiscal months and example queries come from `/v1/meta`, the model's `meta:`, or `model.config.yml`, never from code. Example dashboards, the Cube model, dbt, Airflow and tests may name members; nothing under `dashboard/`, `builder/`, `dashboards/dashspec/`, `lab/`, `admin/`, `auth/` or `cube/cube.js` may. `agent/`, `actions/` and `builder/recipes/` are model add-ons (they belong to one model; a recipe is named by `builder.recipe` in that model's model.config.yml) and are exempt.

- A second, different model lives in `models/distributor/`; the dashspec tests run on both models (`dashboards/tests/test_models.py`).
- `scripts/no_model_names.py` lists the places that break the rule. CI job `no-model-names` runs it with `--strict`: any hit not justified in `scripts/no-model-names.allow` fails the build. Do not add hits; remove them when you touch the file.
- The plan and its phases: [`PLAN-decouple.md`](PLAN-decouple.md).

# What this repo is

An open-source BI stack where **dashboards are YAML files** served from a governed **Cube** semantic layer on **StarRocks**, behind Keycloak sign-in with row-level security. A live AdventureWorks OLTP simulator feeds it through Airflow, ingestr and dbt. `README.md` is long and covers the pipelines, ports and setup; `docs/` has the guides; the `PLAN-*.md` files at the root record the design of each feature (read the relevant one before changing that area).

## Architecture (the parts that span folders)

- **Data path:** `postgres_active` (simulated OLTP) → ingestr (Airflow DAG `postgres_active_to_starrocks`, every 5 min) → StarRocks `raw` → dbt (`dbt/adventureworks_starrocks`) → `mart` → Cube (`cube/`) → dashboard. A separate Kafka/Debezium → ClickHouse CDC path (`--profile cdc`) is independent of it.
- **Models:** `models.yml` is the registry of models (id, Cube model dir, dashboards dir, Cube compose service). A model = Cube model + `model.config.yml` + its dashboards + its own Cube service. Models share only sign-in and people. `models/distributor/` is the second, self-contained one (own Postgres, simulator, RLS rules, `docker-compose.distributor.yml`, compose profile `distributor`).
- **Dashboards as code:** `dashboards/*.yml` (and `models/*/dashboards/`) are validated against `dashboards/schema/dashboard.schema.json` and the Cube model by `dashspec` (`dashboards/dashspec/`), then compiled to JSON. The plain-JS renderer and visual designer (`dashboard/static/render/`) draw the compiled JSON; nginx serves them (`dashboard/cube/nginx.conf.template`, `cube-client.mjs`). There is no JS build step or bundler.
- **Services (FastAPI, each with its own Dockerfile):** `builder/` (prompt → dashboard via an LLM or the rule-based `standin.py`; every answer is checked by `dashspec`; saved dashboards, versions, sharing in Postgres), `auth/` (Keycloak login → short-lived Cube token with the user's row rules), `admin/` (people, groups, rules, datasets over Keycloak and the Postgres `access` schema), `lab/` (SQL lab over Cube's SQL API as the signed-in person), `actions/` and `agent/` (inventory actions; one model's add-ons).
- **Row-level security:** `cube/cube.js`, `cube/rls_registry*.js` and `rls_dimensions.json`; the dimensions are in Postgres (`access.rls_dimension`), and `auth` and `admin` read them on start and won't start without them.
- **Front door:** Caddy (`caddy/`, `docker-compose.public.yml`) routes by path (Keycloak under `/kc`, `/auth-api`, `/admin/`, `/lab/`, …).
- **Postgres init:** `postgres/init/` holds numbered schema scripts and per-service restricted logins (`builder_app`, `access_admin`, `access_auth`, `lab_app`); tests for those services need the matching `*_TEST_PG_DSN` env var to hit a real Postgres.

## Commands

Stack (Compose profiles: default = Postgres + Airflow; `starrocks` = serving path; `cdc`; `distributor`):
```bash
./scripts/generate-env.sh                                   # write .env with random secrets (Compose refuses unset ones)
docker compose --profile starrocks --profile cdc up -d --build
docker compose exec airflow-scheduler airflow dags unpause postgres_active_to_starrocks   # new DAGs start paused
# dashboard: http://localhost:8250 (admin / na_manager / de_rep, password TEST_USER_PASSWORD)
```

Dashboard specs (needs `uv`; the wrapper sets `PYTHONPATH=dashboards`):
```bash
scripts/dashspec validate dashboards/*.yml models/*/dashboards/*.yml
scripts/dashspec compile dashboards/sales-overview.yml -o /tmp/x.json
scripts/dashspec build            # every model's dashboards -> build/<id>.json + index.json
scripts/dashspec meta             # cubes, measures, dimensions a spec may use
```

Tests (mirror `.github/workflows/ci.yml`, which is the source of truth for what runs; many jobs also need real services):
```bash
pre-commit run --all-files                                   # gitleaks, ruff (F, E9, B only; no formatter), whitespace
PYTHONPATH=dashboards python -m pytest dashboards/tests -q   # dashspec; add -k <name> or ::test_x for one test
PYTHONPATH=dashboards:. python -m pytest builder/tests -q    # builder (Postgres tests need BUILDER_TEST_PG_DSN)
python -m pytest auth/tests agent/tests actions/tests/test_rules.py -q
(cd admin && PYTHONPATH=. python -m pytest tests -q)         # lab/ likewise
python scripts/no_model_names.py --strict
node --test dashboard/cube/tests/lib.test.mjs                # one JS unit test; CI lists the full set of *.test.mjs
python -I dashboard/cube/tests/designer.py                   # a browser (Playwright) UI test; others: renderer, admin, home, sharing, lab, models, viewer, builderui
scripts/check-config-js.sh                                   # the dashboard's browser config variants
```
The Playwright UI tests run against `dashboard/cube/tests/mock_stack.py`, so they need no running stack. `scripts/distributor-smoke.sh` is the end-to-end check of the distributor profile.

## Conventions

- CI actions are pinned by commit SHA; keep it that way when editing workflows.
- User-facing strings live in `*-strings.js` files (English and Turkish); add both languages.
- Ruff line length is 100, Python 3.11 target.
