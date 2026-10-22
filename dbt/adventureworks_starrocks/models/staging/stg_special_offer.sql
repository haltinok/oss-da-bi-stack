with source as (
    select * from {{ source('adventureworks', 'special_offer') }}
),

renamed as (
    select
        special_offer_id,
        description,
        discount_pct,
        type,
        category,
        {{ shift_history_date('start_date') }} as start_date,
        {{ shift_history_date('end_date') }} as end_date,
        min_qty,
        max_qty,
        rowguid,
        modified_date
    from source
)

select * from renamed
