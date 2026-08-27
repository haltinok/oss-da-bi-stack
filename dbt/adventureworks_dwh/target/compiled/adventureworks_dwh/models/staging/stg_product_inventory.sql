with source as (
    select * from "analytics_2"."raw"."product_inventory"
),

renamed as (
    select
        product_id,
        location_id,
        shelf,
        bin,
        quantity,
        rowguid,
        modified_date
    from source
)

select * from renamed