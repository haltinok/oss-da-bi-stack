with source as (
    select * from {{ source('adventureworks', 'product_cost_history') }}
),

renamed as (
    select
        product_id,
        start_date,
        end_date,
        standard_cost,
        modified_date
    from source
)

select * from renamed
