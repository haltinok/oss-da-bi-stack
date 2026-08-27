
  create view "analytics_2"."stage"."stg_product_list_price_history__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."product_list_price_history"
),

renamed as (
    select
        product_id,
        start_date,
        end_date,
        list_price,
        modified_date
    from source
)

select * from renamed
  );