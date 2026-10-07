-- Grain check for fact_product_inventory: one row per (product_key, location_key).
-- Dropping location_id used to collapse 1,069 source rows onto 432 distinct
-- product/date pairs; this test fails if the location grain is ever lost again.
select
    product_key,
    location_key,
    count(*) as row_count
from {{ ref('fact_product_inventory') }}
group by product_key, location_key
having count(*) > 1
