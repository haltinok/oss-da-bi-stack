with source as (
    select * from {{ source('adventureworks', 'purchase_order_header') }}
),

renamed as (
    select
        purchase_order_id,
        revision_number,
        status,
        employee_id,
        vendor_id,
        ship_method_id,
        {{ shift_history_date('order_date') }} as order_date,
        {{ shift_history_date('ship_date') }} as ship_date,
        sub_total,
        tax_amt,
        freight,
        total_due,
        modified_date
    from source
)

select * from renamed
