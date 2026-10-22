with source as (
    select * from {{ source('adventureworks', 'purchase_order_detail') }}
),

renamed as (
    select
        purchase_order_id,
        purchase_order_detail_id,
        {{ shift_history_date('due_date') }} as due_date,
        order_qty,
        product_id,
        unit_price,
        line_total,
        received_qty,
        rejected_qty,
        stocked_qty,
        modified_date
    from source
)

select * from renamed
