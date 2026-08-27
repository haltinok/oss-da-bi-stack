with source as (
    select * from {{ source('adventureworks', 'currency') }}
),

renamed as (
    select
        currency_code,
        name,
        modified_date
    from source
)

select * from renamed
