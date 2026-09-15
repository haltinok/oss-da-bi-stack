with source as (
    select * from "analytics"."raw"."department"
),

renamed as (
    select
        department_id,
        name,
        group_name,
        modified_date
    from source
)

select * from renamed