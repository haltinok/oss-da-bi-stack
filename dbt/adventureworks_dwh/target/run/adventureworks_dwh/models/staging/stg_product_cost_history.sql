
  create view "analytics"."stage"."stg_product_cost_history__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics"."raw"."product_cost_history"
),

renamed as (
    select
        product_id,
        start_date,
        end_date,
        standard_cost,
        modified_date
    from source
)

select * from renamed
  );