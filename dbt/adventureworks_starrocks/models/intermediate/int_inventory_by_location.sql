{{ config(materialized='view') }}

-- On-hand stock per product and location.
select
    i.product_id,
    i.location_id,
    l.name as location_name,
    i.quantity
from {{ ref('stg_product_inventory') }} i
left join {{ ref('stg_location') }} l on l.location_id = i.location_id
