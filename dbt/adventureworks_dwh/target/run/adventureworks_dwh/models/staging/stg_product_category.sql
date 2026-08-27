
  create view "analytics_2"."stage"."stg_product_category__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."product_category"
),

renamed as (
    select
        product_category_id,
        name,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );