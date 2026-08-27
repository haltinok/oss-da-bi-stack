with source as (
    select * from "analytics_2"."raw"."address_type"
),

renamed as (
    select
        address_type_id,
        name,
        rowguid,
        modified_date
    from source
)

select * from renamed