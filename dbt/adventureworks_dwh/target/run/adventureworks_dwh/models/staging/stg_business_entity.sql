
  create view "analytics_2"."stage"."stg_business_entity__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."business_entity"
),

renamed as (
    select
        business_entity_id,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );