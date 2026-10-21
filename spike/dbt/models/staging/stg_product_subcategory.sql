with source as (
    select * from {{ source('adventureworks', 'product_subcategory') }}
),

renamed as (
    select
        product_subcategory_id,
        product_category_id,
        name,
        rowguid,
        modified_date
    from source
)

select * from renamed
