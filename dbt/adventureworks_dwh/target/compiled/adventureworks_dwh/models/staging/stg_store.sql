with source as (
    select * from "analytics"."raw"."store"
),

renamed as (
    select
        business_entity_id,
        name,
        sales_person_id,
        demographics,
        rowguid,
        modified_date
    from source
)

select * from renamed