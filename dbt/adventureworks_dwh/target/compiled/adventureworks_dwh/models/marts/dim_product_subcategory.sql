with source as (
    select * from "analytics_2"."stage"."stg_product_subcategory"
),

renamed as (
    select
        product_subcategory_id as product_subcategory_key,
        product_subcategory_id as product_subcategory_alternate_key,
        name as product_subcategory_name,
        product_category_id as product_category_key
    from source
)

select * from renamed