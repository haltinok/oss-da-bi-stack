-- Grain check for the two sales facts: one row per
-- (sales_order_number, sales_order_line_number).
-- A composite key cannot be expressed with dbt's built-in generic tests, so
-- this is a singular test.
with grain as (
    select
        'fact_internet_sales' as source_model,
        sales_order_number,
        sales_order_line_number
    from {{ ref('fact_internet_sales') }}

    union all

    select
        'fact_reseller_sales' as source_model,
        sales_order_number,
        sales_order_line_number
    from {{ ref('fact_reseller_sales') }}
)

select
    source_model,
    sales_order_number,
    sales_order_line_number,
    count(*) as row_count
from grain
group by source_model, sales_order_number, sales_order_line_number
having count(*) > 1
