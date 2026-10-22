{{ config(materialized='table', buckets=2) }}

-- Quantity still to arrive, one row per open purchase-order line or open work order.
-- Purchase: header status 1 (pending) or 2 (approved) and quantity not yet received. A line whose
-- header is missing from the source sample has no status, so the inner join leaves it out: it never
-- counts as on order (see spike/scale/load_supply_sample.py).
-- Manufacture: a work order with no end date and quantity not yet stocked.
-- An open order past its due date still counts as on order; is_overdue flags it.
with as_of as (
    select as_of_date from {{ ref('int_as_of_date') }}
),

purchase as (
    select
        'purchase' as source,
        d.purchase_order_id as order_id,
        d.product_id,
        greatest(d.order_qty - coalesce(d.received_qty, 0), 0) as open_qty,
        d.due_date
    from {{ ref('stg_purchase_order_detail') }} d
    inner join {{ ref('stg_purchase_order_header') }} h on h.purchase_order_id = d.purchase_order_id
    where h.status in (1, 2)
),

manufacture as (
    select
        'manufacture' as source,
        work_order_id as order_id,
        product_id,
        greatest(order_qty - coalesce(stocked_qty, 0), 0) as open_qty,
        due_date
    from {{ ref('stg_work_order') }}
    where end_date is null
),

open_orders as (
    select * from purchase
    union all
    select * from manufacture
)

select
    o.source,
    o.order_id,
    o.product_id,
    o.open_qty,
    o.due_date,
    o.due_date < a.as_of_date as is_overdue
from open_orders o
cross join as_of a
where o.open_qty > 0
