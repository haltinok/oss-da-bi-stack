with source as (
    select * from {{ source('adventureworks', 'shift') }}
),

renamed as (
    select
        shift_id,
        name,
        start_time,
        end_time,
        modified_date
    from source
)

select * from renamed
