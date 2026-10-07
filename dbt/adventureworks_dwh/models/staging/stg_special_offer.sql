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
        start_date,
        end_date,
        min_qty,
        max_qty,
        rowguid,
        modified_date
    from source
)

select * from renamed
