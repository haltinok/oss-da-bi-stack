with source as (
    select * from {{ source('adventureworks', 'special_offer_product') }}
),

renamed as (
    select
        special_offer_id,
        product_id,
        rowguid,
        modified_date
    from source
)

select * from renamed
