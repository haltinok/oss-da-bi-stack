{{ config(materialized='view') }}

-- Type 2 product price history: one row per product version with its validity
-- window (same columns as the Postgres project's dim_product_history, derived
-- from the append-only product_versions log instead of a dbt snapshot).
select
    product_id,
    product_name,
    product_number,
    list_price,
    standard_cost,
    valid_from as dbt_valid_from,
    lead(valid_from) over (partition by product_id order by valid_from) as dbt_valid_to,
    lead(valid_from) over (partition by product_id order by valid_from) is null as is_current
from {{ ref('product_versions') }}
