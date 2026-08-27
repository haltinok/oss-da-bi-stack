with source as (
    select * from {{ source('adventureworks', 'address_type') }}
),

renamed as (
    select
        address_type_id,
        name,
        rowguid,
        modified_date
    from source
)

select * from renamed
