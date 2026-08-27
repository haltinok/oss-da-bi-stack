with source as (
    select * from "analytics_2"."raw"."vendor"
),

renamed as (
    select
        business_entity_id,
        account_number,
        name,
        credit_rating,
        preferred_vendor_status,
        active_flag,
        purchasing_web_service_url,
        modified_date
    from source
)

select * from renamed