with inventory as (
    select * from "analytics_2"."stage"."stg_product_inventory"
),

renamed as (
    select
        product_id as product_key,
        to_char(modified_date, 'YYYYMMDD')::int as date_key,
        modified_date as movement_date,
        quantity as units_balance
    from inventory
)

select * from renamed