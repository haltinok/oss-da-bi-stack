# Rules for working in this repo

## The app knows no model
Cube names, member names, channels, fiscal months and example queries come from `/v1/meta`, the model's `meta:`, or `model.config.yml`, never from code. Example dashboards, the Cube model, dbt, Airflow and tests may name members; nothing under `dashboard/`, `builder/`, `dashboards/dashspec/`, `lab/`, `admin/`, `auth/` or `cube/cube.js` may. `agent/`, `actions/` and `builder/recipes/` are model add-ons (they belong to one model; a recipe is named by `builder.recipe` in that model's model.config.yml) and are exempt.

- A second, different model lives in `models/distributor/`; the dashspec tests run on both models (`dashboards/tests/test_models.py`).
- `scripts/no_model_names.py` lists the places that break the rule (CI job `no-model-names`; a warning until PLAN-decouple.md phase 5 makes it an error). Do not add hits; remove them when you touch the file.
- The plan and its phases: [`PLAN-decouple.md`](PLAN-decouple.md).
