# dbt-starrocks star schema (spike Phase 3)

StarRocks port of `dbt/adventureworks_dwh` (which stays Postgres). Reads the Phase 2
schemas (`scale_10m` / `scale_100m` / `scale_500m`, or `raw`) and builds `stage.*`
views and `mart.*` tables.

```bash
cd spike/dbt
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
. .venv/bin/activate
dbt run  --profiles-dir . --vars '{aw_source_schema: scale_10m}' --full-refresh
dbt test --profiles-dir . --vars '{aw_source_schema: scale_10m}'
```

Connection comes from `DBT_SR_*` env vars (defaults match the spike stack: 127.0.0.1:9030, root, no password).

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
- `date_shift_years: 0`: the scaled data already spans 2011-2021.
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
