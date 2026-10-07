with source as (
    select * from {{ source('adventureworks', 'customer') }}
),

renamed as (
    select
        customer_id,
        person_id,
        store_id,
        territory_id,
        account_number,
        rowguid,
        modified_date
    from source
)

select * from renamed
