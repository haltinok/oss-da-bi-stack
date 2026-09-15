
  create view "analytics"."stage"."stg_currency__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics"."raw"."currency"
),

renamed as (
    select
        currency_code,
        name,
        modified_date
    from source
)

select * from renamed
  );