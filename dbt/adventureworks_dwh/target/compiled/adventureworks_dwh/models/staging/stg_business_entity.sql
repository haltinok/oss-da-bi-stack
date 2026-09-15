with source as (
    select * from "analytics"."raw"."business_entity"
),

renamed as (
    select
        business_entity_id,
        rowguid,
        modified_date
    from source
)

select * from renamed