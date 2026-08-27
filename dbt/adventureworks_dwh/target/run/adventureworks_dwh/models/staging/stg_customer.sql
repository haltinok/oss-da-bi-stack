
  create view "analytics_2"."stage"."stg_customer__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."customer"
),

renamed as (
    select
        customer_id,
        person_id,
        store_id,
        territory_id,
        account_number,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );