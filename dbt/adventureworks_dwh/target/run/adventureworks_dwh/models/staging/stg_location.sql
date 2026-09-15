
  create view "analytics"."stage"."stg_location__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics"."raw"."location"
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
  );