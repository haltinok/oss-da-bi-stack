{{ config(
    table_type='DUPLICATE',
    keys=['order_date', 'sales_order_number', 'sales_order_line_number'],
    partition_type='Expr',
    partition_by=["date_trunc('month', order_date)"],
    distributed_by=['product_key'],
    buckets=4,
) }}

-- Online (web) sales order lines.
-- Grain: one row per (sales_order_number, sales_order_line_number).
-- Shared line/measure logic lives in int_sales_order_lines.
with lines as (
    select * from {{ ref('int_sales_order_lines') }}
    where channel = 'internet'
)

select
    order_date,
    sales_order_number,
    sales_order_line_number,
    product_id as product_key,
    order_date_key,
    due_date_key,
    ship_date_key,
    customer_id as customer_key,
    special_offer_id as promotion_key,
    currency_code as currency_key,
    territory_id as sales_territory_key,
    order_status,
    revision_number,
    order_quantity,
    unit_price,
    extended_amount,
    unit_price_discount_pct,
    discount_amount,
    product_standard_cost,
    total_product_cost,
    sales_amount,
    tax_amt,
    freight,
    carrier_tracking_number,
    customer_po_number,
    due_date,
    ship_date
from lines
