
  create view "analytics_2"."stage"."stg_address__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."address"
),

renamed as (
    select
        address_id,
        address_line1,
        address_line2,
        city,
        state_province_id,
        postal_code,
        spatial_location,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );