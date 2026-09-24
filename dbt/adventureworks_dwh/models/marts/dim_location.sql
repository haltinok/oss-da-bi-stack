-- Stocking locations (warehouses) referenced by fact_product_inventory.
with source as (
    select * from {{ ref('stg_location') }}
),

renamed as (
    select
        location_id as location_key,
        location_id as location_alternate_key,
        name as location_name,
        cost_rate,
        availability
    from source
)

select * from renamed
