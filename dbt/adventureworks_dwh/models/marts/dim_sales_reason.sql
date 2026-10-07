with source as (
    select * from {{ ref('stg_sales_reason') }}
),

renamed as (
    select
        sales_reason_id as sales_reason_key,
        sales_reason_id as sales_reason_alternate_key,
        name as sales_reason_name,
        reason_type as sales_reason_reason_type
    from source
)

select * from renamed
