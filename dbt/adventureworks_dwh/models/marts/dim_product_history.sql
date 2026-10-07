-- Type 2 product price history.
--
-- dim_product is Type 1 (it keeps only the current row), so the SCD2 history
-- lives in the `dim_product_snapshot` snapshot, which `dbt build` maintains.
-- This model is its consumer: one row per product version, with the validity
-- window. Use it to answer "what was the list price on date X".
select
    product_id,
    name as product_name,
    product_number,
    list_price,
    standard_cost,
    dbt_valid_from,
    dbt_valid_to,
    dbt_valid_to is null as is_current
from {{ ref('dim_product_snapshot') }}
