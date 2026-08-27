with source as (
    select * from "analytics_2"."raw"."product_product_photo"
),

renamed as (
    select
        product_id,
        product_photo_id,
        "primary",
        modified_date
    from source
)

select * from renamed