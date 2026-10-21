{{ config(materialized='table', table_type='PRIMARY', keys=['product_id', 'order_date'],
          distributed_by=['product_id'], buckets=4) }}

-- Standard cost in effect for every (product, order date) that can occur: the
-- latest cost-history row starting on or before the date. The Postgres model
-- derived this from the order lines with DISTINCT ON; at 500M lines that means
-- joining the whole fact to the history, so here the candidate pairs come from
-- the (small) product x date cross product instead and the fact joins to this.
with products as (
    select distinct product_id from {{ ref('stg_sales_order_detail') }}
),

dates as (
    select distinct order_date from {{ ref('stg_sales_order_header') }}
),

ranked as (
    select
        p.product_id,
        d.order_date,
        pch.standard_cost,
        row_number() over (
            partition by p.product_id, d.order_date
            order by pch.start_date desc
        ) as rn
    from products p
    cross join dates d
    inner join {{ ref('stg_product_cost_history') }} pch
        on pch.product_id = p.product_id
        and pch.start_date <= d.order_date
)

select product_id, order_date, standard_cost
from ranked
where rn = 1
