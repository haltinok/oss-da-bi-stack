with source as (
    select * from "analytics_2"."raw"."sales_territory"
),

renamed as (
    select
        territory_id,
        name,
        country_region_code,
        "group",
        sales_ytd,
        sales_last_year,
        cost_ytd,
        cost_last_year,
        rowguid,
        modified_date
    from source
)

select * from renamed