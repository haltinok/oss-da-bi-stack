with source as (
    select * from {{ ref('stg_currency') }}
),

renamed as (
    select
        currency_code as currency_key,
        currency_code as currency_alternate_key,
        name as currency_name
    from source
)

select * from renamed
