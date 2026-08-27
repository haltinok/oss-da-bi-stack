with source as (
    select * from "analytics_2"."raw"."business_entity_address"
),

renamed as (
    select
        business_entity_id,
        address_id,
        address_type_id,
        rowguid,
        modified_date
    from source
)

select * from renamed