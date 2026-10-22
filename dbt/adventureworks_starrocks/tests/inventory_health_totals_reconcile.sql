-- The headline totals must equal an independent recomputation from the source tables, so a change to the
-- joins cannot silently double-count: excess value from stock and standard cost, order value from unit cost.
with m as (
    select sum(excess_value) as excess_value, sum(suggested_order_value) as order_value, sum(excess_units) as excess_units
    from {{ ref('inventory_health') }}
),

direct as (
    select
        sum(h.excess_units * p.standard_cost) as excess_value,
        sum(h.suggested_order_qty * coalesce(r.unit_cost, 0)) as order_value
    from {{ ref('inventory_health') }} h
    inner join {{ ref('stg_product') }} p on p.product_id = h.product_key
    inner join {{ ref('int_product_replenishment') }} r on r.product_id = h.product_key
)

select m.excess_value, direct.excess_value as direct_excess_value, m.order_value, direct.order_value as direct_order_value
from m cross join direct
where abs(coalesce(m.excess_value, 0) - coalesce(direct.excess_value, 0)) > 0.01
   or abs(coalesce(m.order_value, 0) - coalesce(direct.order_value, 0)) > 0.01
