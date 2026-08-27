
  create view "analytics_2"."stage"."stg_email_address__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."email_address"
),

renamed as (
    select
        business_entity_id,
        email_address_id,
        email_address,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );