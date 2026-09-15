
  create view "analytics"."stage"."stg_shift__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics"."raw"."shift"
),

renamed as (
    select
        shift_id,
        name,
        start_time,
        end_time,
        modified_date
    from source
)

select * from renamed
  );