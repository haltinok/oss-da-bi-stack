-- A reorder quantity is never negative, and only stockout / reorder_now products get one.
select product_key, status, suggested_order_qty
from {{ ref('inventory_health') }}
where suggested_order_qty < 0
   or (suggested_order_qty > 0 and status not in ('stockout', 'reorder_now'))
