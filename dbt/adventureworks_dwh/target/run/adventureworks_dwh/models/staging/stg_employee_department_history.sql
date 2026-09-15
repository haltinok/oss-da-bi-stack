
  create view "analytics"."stage"."stg_employee_department_history__dbt_tmp"
    
    
  as (
    with source as (
    select * from "analytics"."raw"."employee_department_history"
),

renamed as (
    select
        business_entity_id,
        department_id,
        shift_id,
        start_date,
        end_date,
        modified_date
    from source
)

select * from renamed
  );