with source as (
    select * from {{ source('adventureworks', 'sales_order_detail') }}
    {% if var('use_pk_snapshots', false) %}
    -- Lines of a deleted order go with it (see stg_sales_order_header).
    where sales_order_id in (select sales_order_id from {{ source('adventureworks', 'pk_sales_order_header') }})
    {% endif %}
),

renamed as (
    select
        sales_order_id,
        sales_order_detail_id,
        carrier_tracking_number,
        order_qty,
        product_id,
        special_offer_id,
        unit_price,
        unit_price_discount,
        line_total,
        rowguid,
        modified_date
    from source
)

select * from renamed
