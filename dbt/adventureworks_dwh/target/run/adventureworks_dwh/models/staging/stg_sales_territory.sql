
  create view "analytics"."stage"."stg_sales_territory__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics"."raw"."sales_territory"
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
  );