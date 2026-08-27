
  
    

  create  table "analytics_2"."mart"."dim_promotion__dbt_tmp"
  
  
    as
  
  (
    with source as (
    select * from "analytics_2"."stage"."stg_special_offer"
),

renamed as (
    select
        special_offer_id as promotion_key,
        special_offer_id as promotion_alternate_key,
        description as promotion_name,
        discount_pct,
        type as promotion_type,
        category as promotion_category,
        start_date,
        end_date,
        min_qty,
        max_qty
    from source
)

select * from renamed
  );
  