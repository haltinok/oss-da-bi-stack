
  create view "analytics_2"."stage"."stg_state_province__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."state_province"
),

renamed as (
    select
        state_province_id,
        state_province_code,
        country_region_code,
        is_only_state_province_flag,
        name,
        territory_id,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );