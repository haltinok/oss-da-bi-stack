
  
    

  create  table "analytics_2"."mart"."dim_sales_territory__dbt_tmp"
  
  
    as
  
  (
    with source as (
    select * from "analytics_2"."stage"."stg_sales_territory"
),

renamed as (
    select
        territory_id as sales_territory_key,
        territory_id as sales_territory_alternate_key,
        name as sales_territory_region,
        country_region_code as sales_territory_country,
        "group" as sales_territory_group
    from source
)

select * from renamed
  );
  