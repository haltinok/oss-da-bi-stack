
  create view "analytics_2"."stage"."stg_currency__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."currency"
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