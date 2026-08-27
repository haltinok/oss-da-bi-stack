
  
    

  create  table "analytics_2"."mart"."dim_product__dbt_tmp"
  
  
    as
  
  (
    with product as (
    select * from "analytics_2"."stage"."stg_product"
),

subcategory as (
    select * from "analytics_2"."stage"."stg_product_subcategory"
),

category as (
    select * from "analytics_2"."stage"."stg_product_category"
),

renamed as (
    select
        p.product_id as product_key,
        p.product_id as product_alternate_key,
        p.product_subcategory_id as product_subcategory_key,
        p.weight_unit_measure_code,
        p.size_unit_measure_code,
        p.name as product_name,
        p.standard_cost,
        p.finished_goods_flag,
        p.color,
        p.safety_stock_level,
        p.reorder_point,
        p.list_price,
        p.size,
        p.weight,
        p.days_to_manufacture,
        p.product_line,
        p.class,
        p.style,
        p.product_model_id,
        p.sell_start_date as start_date,
        p.sell_end_date as end_date,
        case
            when p.sell_end_date is null or p.sell_end_date > current_date then 'Current'
            else 'Discontinued'
        end as status,
        sub.product_subcategory_id is not null as has_subcategory,
        cat.name as product_category_name,
        sub.name as product_subcategory_name
    from product p
    left join subcategory sub on p.product_subcategory_id = sub.product_subcategory_id
    left join category cat on sub.product_category_id = cat.product_category_id
)

select * from renamed
  );
  