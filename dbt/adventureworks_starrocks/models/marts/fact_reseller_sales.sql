{{ config(
    materialized='incremental',
    unique_key=['order_date', 'sales_order_number', 'sales_order_line_number'],
    keys=['order_date', 'sales_order_number', 'sales_order_line_number'],
    table_type='PRIMARY',
    partition_type='Expr',
    partition_by=["date_trunc('month', order_date)"],
    distributed_by=['sales_order_number'],
    buckets=4,
    post_hook=["{{ delete_removed_orders() }}"],
) }}

-- Reseller (distributor) sales order lines.
-- Grain: one row per (sales_order_number, sales_order_line_number).
-- Incremental upsert (primary-key table): see macros/sales_order_lines.sql.
with lines as (
    {{ sales_order_lines('reseller') }}
)

select
    order_date,
    sales_order_number,
    sales_order_line_number,
    product_id as product_key,
    order_date_key,
    due_date_key,
    ship_date_key,
    reseller_customer_id as reseller_key,
    sales_person_id as employee_key,
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
    ship_date,
    source_modified_date
from lines
