
  
    

  create  table "analytics"."mart"."dim_product_category__dbt_tmp"
  
  
    as
  
  (
    with source as (
    select * from "analytics"."stage"."stg_product_category"
),

renamed as (
    select
        product_category_id as product_category_key,
        product_category_id as product_category_alternate_key,
        name as product_category_name
    from source
)

select * from renamed
  );
  