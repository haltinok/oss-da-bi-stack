with source as (
    select * from "analytics_2"."raw"."sales_person_quota_history"
),

renamed as (
    select
        business_entity_id,
        quota_date,
        sales_quota,
        rowguid,
        modified_date
    from source
)

select * from renamed