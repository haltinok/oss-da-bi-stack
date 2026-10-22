with source as (
    select * from {{ source('adventureworks', 'product_category') }}
),

renamed as (
    select
        product_category_id,
        name,
        rowguid,
        modified_date
    from source
)

select * from renamed
