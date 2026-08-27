
  create view "analytics_2"."stage"."stg_special_offer__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."special_offer"
),

renamed as (
    select
        special_offer_id,
        description,
        discount_pct,
        type,
        category,
        start_date,
        end_date,
        min_qty,
        max_qty,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );