with source as (
    select * from "analytics_2"."raw"."employee"
),

renamed as (
    select
        business_entity_id,
        national_id_number,
        login_id,
        organization_node,
        organization_level,
        job_title,
        birth_date,
        marital_status,
        gender,
        hire_date,
        salaried_flag,
        vacation_hours,
        sick_leave_hours,
        current_flag,
        rowguid,
        modified_date
    from source
)

select * from renamed