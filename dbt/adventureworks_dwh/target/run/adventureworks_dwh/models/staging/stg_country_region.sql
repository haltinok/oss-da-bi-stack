
  create view "analytics"."stage"."stg_country_region__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics"."raw"."country_region"
),

renamed as (
    select
        country_region_code,
        name,
        modified_date
    from source
)

select * from renamed
  );