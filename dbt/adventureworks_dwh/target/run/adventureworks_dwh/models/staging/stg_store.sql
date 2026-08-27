
  create view "analytics_2"."stage"."stg_store__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."store"
),

renamed as (
    select
        business_entity_id,
        name,
        sales_person_id,
        demographics,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );