with source as (
    select * from {{ source('adventureworks', 'sales_reason') }}
),

renamed as (
    select
        sales_reason_id,
        name,
        reason_type,
        modified_date
    from source
)

select * from renamed
