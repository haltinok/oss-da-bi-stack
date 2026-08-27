
  create view "analytics_2"."stage"."stg_sales_order_detail__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."sales_order_detail"
),

renamed as (
    select
        sales_order_id,
        sales_order_detail_id,
        carrier_tracking_number,
        order_qty,
        product_id,
        special_offer_id,
        unit_price,
        unit_price_discount,
        line_total,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );