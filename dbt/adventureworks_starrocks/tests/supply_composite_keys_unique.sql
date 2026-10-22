-- Composite primary keys of the supply tables (a column-level unique test cannot express them).
select 'product_inventory' as tbl, product_id, location_id, count(*) as n
from {{ ref('stg_product_inventory') }} group by product_id, location_id having count(*) > 1
union all
select 'product_vendor', product_id, business_entity_id, count(*)
from {{ ref('stg_product_vendor') }} group by product_id, business_entity_id having count(*) > 1
union all
select 'purchase_order_detail', purchase_order_id, purchase_order_detail_id, count(*)
from {{ ref('stg_purchase_order_detail') }} group by purchase_order_id, purchase_order_detail_id having count(*) > 1
union all
select 'special_offer_product', special_offer_id, product_id, count(*)
from {{ ref('stg_special_offer_product') }} group by special_offer_id, product_id having count(*) > 1
