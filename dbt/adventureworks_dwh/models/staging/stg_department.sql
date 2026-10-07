with source as (
    select * from {{ source('adventureworks', 'department') }}
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
