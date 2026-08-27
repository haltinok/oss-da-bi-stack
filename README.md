# Open-Source D&A Stack

Redshift → (dlt) → Postgres `raw` → (dbt-core) → Postgres `stage` → Postgres `data_mart` → (Superset)
Orchestrated end-to-end by Airflow.

## Stack

| Layer            | Tool        |
|-------------------|-------------|
| Orchestration      | Airflow 3.3.1 (LocalExecutor) |
| Ingestion           | dlt |
| Transformation      | dbt-core |
| Database/warehouse  | Postgres |
| Reporting/dashboarding | Superset |

One Postgres **instance** hosts three **databases**:
- `airflow` — Airflow's own metadata (internal implementation detail, not part of the analytics layer)
- `superset_meta` — Superset's own metadata: dashboards, charts, users, saved queries (also just an implementation detail, not data you'd report on)
- `analytics` — the actual warehouse, with three schemas: `raw` (dlt lands data here), `stage` (dbt staging views), `data_mart` (dbt mart tables, what Superset reads from)

## Folder structure

```
oss-data-stack/
├── docker-compose.yml
├── .env.example              # copy to .env and fill in
├── airflow/
│   ├── Dockerfile            # apache/airflow:3.3.1 + dlt + dbt-core installed
│   ├── requirements.txt
│   └── dags/
│       └── redshift_to_postgres_dag.py
├── dlt/
│   └── pipelines/
│       └── redshift_to_postgres/
│           ├── redshift_pipeline.py
│           └── .dlt/
│               ├── config.toml       # non-secret settings
│               └── secrets.toml      # fill in real creds, keep out of git
├── dbt/
│   └── data_mart/
│       ├── dbt_project.yml
│       ├── profiles.yml
│       ├── macros/
│       │   └── generate_schema_name.sql
│       └── models/
│           ├── staging/
│           │   ├── _sources.yml
│           │   └── stg_your_table_name.sql
│           └── marts/
│               └── dim_your_table_name.sql
├── postgres/
│   └── init/
│       └── 01_init.sql       # creates airflow db + analytics db + schemas
└── superset/
    ├── Dockerfile
    └── superset_config.py
```

## Setup

1. **Copy env template:**
   ```bash
   cp .env.example .env
   # generate real values for AIRFLOW_FERNET_KEY, AIRFLOW_WEBSERVER_SECRET_KEY, SUPERSET_SECRET_KEY
   ```

2. **Fill in real credentials** in `dlt/pipelines/redshift_to_postgres/.dlt/secrets.toml` (Redshift source creds; Postgres destination user/password already match the compose defaults). Add this file to `.gitignore` before pushing anywhere public.

3. **Generate the dlt source module once**, from your host machine (needs `uv`/`dlt` installed locally, or run inside the airflow container after first build):
   ```bash
   cd dlt/pipelines/redshift_to_postgres
   dlt init sql_database postgres
   ```
   This drops a `sql_database/` module next to `redshift_pipeline.py` — it's what makes `from sql_database import sql_database` work. Then edit `redshift_pipeline.py` to select your actual Redshift table(s).

4. **Edit the dbt source/model stubs** in `dbt/data_mart/models/` — `_sources.yml` and the two example `.sql` files currently reference a placeholder `your_table_name`; swap in your real table names.

5. **Bring the stack up:**
   ```bash
   docker compose up -d --build
   ```
   First run takes a while (image builds + `airflow-init` + `superset-init`).

6. **Access:**
   - Airflow UI (served by the api-server): http://localhost:8080 (user/pass from `.env`)
   - Superset UI: http://localhost:8088 (admin/admin unless changed)
   - Postgres: `localhost:5432`, db `analytics`, user/pass `postgres`/`postgres` (Superset's own metadata lives in a separate `superset_meta` database on the same instance — you won't need to touch it directly)

7. **In Superset**, add a new database connection to `postgresql://postgres:postgres@postgres:5432/analytics` (use the Docker service name `postgres`, not `localhost`, since Superset is calling it from inside the compose network) and build charts/dashboards against the `data_mart` schema.

8. **Trigger the DAG** (`redshift_to_postgres_elt`) from the Airflow UI, or unpause it to let the daily schedule take over. It runs: `dlt ingest → dbt run --select staging → dbt run --select marts → dbt test`.

## Notes

- LocalExecutor keeps this lean (no Redis/Celery workers) — fine for a portfolio/demo stack or small real workloads; swap to CeleryExecutor if you outgrow it.
- Airflow 3 split the old monolithic webserver into separate components — `airflow-api-server` (UI + REST API), `airflow-scheduler`, `airflow-dag-processor` (DAG parsing, split out of the scheduler), and `airflow-triggerer` (deferrable tasks). All four run as separate services here, matching Airflow's own reference compose layout.
- Airflow 3's default auth manager (Simple Auth Manager) doesn't support the env-var-provisioned admin user the way 2.x did. `apache-airflow-providers-fab` is installed and `AIRFLOW__CORE__AUTH_MANAGER` is set to `FabAuthManager` specifically to keep the `_AIRFLOW_WWW_USER_USERNAME`/`_PASSWORD` workflow you're used to.
- dlt's `PipelineTasksGroup` Airflow helper (from `dlt.helpers.airflow_helper`) is currently broken on Airflow 3.x — it imports `DummyOperator` from a module path Airflow 3 removed. The DAG here sidesteps this entirely by using plain `BashOperator` to shell out to the pipeline script, so it's unaffected. If you later want per-resource task granularity via `PipelineTasksGroup`, that requires Airflow 2.x until dlt patches the import.
- Pinned versions in `airflow/requirements.txt` are reasonable as of writing — bump them and rebuild if you hit compatibility issues, especially the Airflow base image tag in `airflow/Dockerfile`.
- `write_disposition="merge"` in the dlt pipeline requires a primary key dlt can detect (or pass one explicitly via `sql_database(...).table_name.apply_hints(primary_key=...)`) — otherwise switch to `"append"` or `"replace"`.
