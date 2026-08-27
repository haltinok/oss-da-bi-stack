with source as (
    select * from {{ source('adventureworks', 'sales_order_header_sales_reason') }}
),

renamed as (
    select
        sales_order_id,
        sales_reason_id,
        modified_date
    from source
)

select * from renamed
