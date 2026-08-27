
  create view "analytics_2"."stage"."stg_sales_person__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."sales_person"
),

renamed as (
    select
        business_entity_id,
        territory_id,
        sales_quota,
        bonus,
        commission_pct,
        sales_ytd,
        sales_last_year,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );