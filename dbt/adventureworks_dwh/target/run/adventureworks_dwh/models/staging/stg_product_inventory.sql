
  create view "analytics_2"."stage"."stg_product_inventory__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."product_inventory"
),

renamed as (
    select
        product_id,
        location_id,
        shelf,
        bin,
        quantity,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );