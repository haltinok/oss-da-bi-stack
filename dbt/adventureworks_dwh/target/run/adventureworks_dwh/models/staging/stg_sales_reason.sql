
  create view "analytics_2"."stage"."stg_sales_reason__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."sales_reason"
),

renamed as (
    select
        sales_reason_id,
        name,
        reason_type,
        modified_date
    from source
)

select * from renamed
  );