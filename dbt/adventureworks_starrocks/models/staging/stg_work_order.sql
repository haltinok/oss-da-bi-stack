with source as (
    select * from {{ source('adventureworks', 'work_order') }}
),

renamed as (
    select
        work_order_id,
        product_id,
        order_qty,
        stocked_qty,
        scrapped_qty,
        {{ shift_history_date('start_date') }} as start_date,
        {{ shift_history_date('end_date') }} as end_date,
        {{ shift_history_date('due_date') }} as due_date,
        scrap_reason_id,
        modified_date
    from source
)

select * from renamed
