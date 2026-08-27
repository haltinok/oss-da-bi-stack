with source as (
    select * from "analytics_2"."raw"."employee_department_history"
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