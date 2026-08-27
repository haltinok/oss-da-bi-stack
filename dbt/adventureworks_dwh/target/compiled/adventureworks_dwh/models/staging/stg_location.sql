with source as (
    select * from "analytics_2"."raw"."location"
),

renamed as (
    select
        location_id,
        name,
        cost_rate,
        availability,
        modified_date
    from source
)

select * from renamed