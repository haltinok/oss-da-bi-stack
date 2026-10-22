# dbt-starrocks star schema

The star schema on StarRocks (it replaced the dbt-postgres project `dbt/adventureworks_dwh`, now in git history).
By default it reads the live `raw` schema loaded by the `postgres_active_to_starrocks` DAG and builds
`stage.*` views, `mart.*` tables and the small `rls.*` schema the auth service reads. It can also read the
benchmark schemas of the spike (`scale_10m` / `scale_100m` / `scale_500m`, built by `spike/scale`).

The pipeline runs it as `dbt build --vars '{aw_source_schema: raw, use_pk_snapshots: true}'`. By hand
(StarRocks reachable on the host, e.g. `STARROCKS_MYSQL_PORT` from `.env`):

```bash
cd dbt/adventureworks_starrocks
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
. .venv/bin/activate
DBT_SR_PORT=9030 dbt build --profiles-dir . --vars '{aw_source_schema: raw, use_pk_snapshots: true}'
# a benchmark scale instead (their dates already span 2011-2021, so no history shift):
dbt run --profiles-dir . --vars '{aw_source_schema: scale_10m, date_shift_years: 0}' --full-refresh
```

Connection comes from `DBT_SR_*` env vars (defaults: 127.0.0.1:9030, root, no password).

## Marts
Dims are Primary Key tables; facts are duplicate-key tables partitioned by month on
`order_date`, distributed by `product_key`.

| Model | Notes |
|---|---|
| `dim_date`, `dim_product`, `dim_sales_territory`, `dim_geography`, `dim_customer` | ported; same columns as the Postgres marts |
| `fact_internet_sales`, `fact_reseller_sales` | same columns; key columns reordered to lead the table |
| `product_versions` + `dim_product_history` | SCD2, insert-only (see below) |

Keys stay the AdventureWorks integer ids (`product_key = product_id`, ...), as in the
Postgres marts, rather than newly minted surrogates.
Not ported (the dashboard does not read them): `dim_promotion`, `dim_currency`,
`dim_reseller`, `dim_employee`, inventory/quota/rate facts.

## Differences from the Postgres project
- `distinct on` -> `row_number()`; `to_char(...)::int` -> `cast(date_format(...) as int)`; `generate_series` -> `table(generate_series(...))`; `"group"` -> `` `group` ``.
- `product_cost_daily` (new): standard cost per (product, order date) built from the small
  product x date cross product, instead of `distinct on` over the whole fact.
- `sales_order_line_number` is numbered in a two-column subquery. Numbering it inside the
  wide `order_lines` CTE ran StarRocks out of memory at 10M lines.
- `date_shift_years: 12` (as in the Postgres project) so the seeded history meets the live orders; the
  benchmark schemas must pass `date_shift_years: 0`.
- `data_version` (one row, rewritten every build) lets Cube refresh its rollups when the mart changed;
  `models/rls/user_regions` is the auth service's table (see `starrocks/init.sh` for why it is its own schema).
- `use_pk_snapshots: true` drops orders deleted at the source (a merge load never sees deletes).
- `dbt snapshot` is replaced by `product_versions` (see findings).

## Findings
- **dbt-starrocks 1.12.2 needs `mysql-connector-python==8.4.0`**; newer releases fail with
  "property 'server_version' ... has no setter".
- **`dbt snapshot` does not work.** The adapter's snapshot merge issues a MySQL multi-table
  `UPDATE t, (...) SET ...` which StarRocks rejects, and the snapshot table is duplicate-key
  (no UPDATE). Insert-only `product_versions` (incremental, PK table) + a `lead()` view gives
  the same SCD2 history; verified: price change -> 2 versions, closed window, one current;
  re-run without change adds nothing.
- **Key columns must lead the table** in CTAS (PRIMARY/DUPLICATE KEY), so the model SELECT
  order matters.
- **Memory:** wide windows and concurrent big CTAS runs hit the BE limit (see timings in `results.md`).
  Run the two facts sequentially (`--threads 1`) at 100M+; 500M needs `enable_spill`.
- Default `query_timeout` (300 s) kills the larger builds: `SET GLOBAL query_timeout=7200`.
