with source as (
    select * from {{ source('adventureworks', 'product_cost_history') }}
),

renamed as (
    select
        product_id,
        {{ shift_history_date('start_date') }} as start_date,
        {{ shift_history_date('end_date') }} as end_date,
        standard_cost,
        modified_date
    from source
)

select * from renamed
