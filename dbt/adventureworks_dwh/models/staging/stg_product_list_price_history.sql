with source as (
    select * from {{ source('adventureworks', 'product_list_price_history') }}
),

renamed as (
    select
        product_id,
        start_date,
        end_date,
        list_price,
        modified_date
    from source
)

select * from renamed
