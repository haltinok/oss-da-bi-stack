
  create view "analytics_2"."stage"."stg_product_subcategory__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."product_subcategory"
),

renamed as (
    select
        product_subcategory_id,
        product_category_id,
        name,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );