
  
    

  create  table "analytics_2"."mart"."dim_product_category__dbt_tmp"
  
  
    as
  
  (
    with source as (
    select * from "analytics_2"."stage"."stg_product_category"
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
  