with source as (
    select * from "analytics_2"."raw"."email_address"
),

renamed as (
    select
        business_entity_id,
        email_address_id,
        email_address,
        rowguid,
        modified_date
    from source
)

select * from renamed