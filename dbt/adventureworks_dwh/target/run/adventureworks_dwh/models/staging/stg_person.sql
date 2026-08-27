
  create view "analytics_2"."stage"."stg_person__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics_2"."raw"."person"
),

renamed as (
    select
        business_entity_id,
        person_type,
        name_style,
        title,
        first_name,
        middle_name,
        last_name,
        suffix,
        email_promotion,
        additional_contact_info,
        demographics,
        rowguid,
        modified_date
    from source
)

select * from renamed
  );