with source as (
    select * from {{ source('adventureworks', 'product_vendor') }}
),

renamed as (
    select
        product_id,
        business_entity_id,
        average_lead_time,
        standard_price,
        last_receipt_cost,
        {{ shift_history_date('last_receipt_date') }} as last_receipt_date,
        min_order_qty,
        max_order_qty,
        on_order_qty,
        unit_measure_code,
        modified_date
    from source
)

select * from renamed
