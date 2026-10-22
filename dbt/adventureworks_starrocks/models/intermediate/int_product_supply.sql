{{ config(materialized='table', table_type='PRIMARY', keys=['product_id'], distributed_by=['product_id'], buckets=2) }}

-- Per product: stock on hand (all locations), whether the product is stocked anywhere at all
-- (any inventory row), and what is already on order.
with inventory as (
    select product_id, sum(quantity) as on_hand, count(*) as stocked_locations
    from {{ ref('stg_product_inventory') }}
    group by product_id
),

open_orders as (
    select product_id, sum(open_qty) as on_order, min(due_date) as next_due_date
    from {{ ref('int_open_replenishment') }}
    group by product_id
)

select
    p.product_id,
    coalesce(i.on_hand, 0) as on_hand,
    coalesce(i.stocked_locations, 0) as stocked_locations,
    coalesce(o.on_order, 0) as on_order,
    o.next_due_date
from {{ ref('stg_product') }} p
left join inventory i on i.product_id = p.product_id
left join open_orders o on o.product_id = p.product_id
