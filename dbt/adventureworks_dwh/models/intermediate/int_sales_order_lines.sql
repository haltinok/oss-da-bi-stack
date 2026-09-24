{{ config(materialized='ephemeral') }}

-- Per-order-line grain shared by fact_internet_sales and fact_reseller_sales.
--
-- Both facts used to carry byte-identical copies of the `order_lines` and
-- `product_cost` logic; the only real differences are the channel filter and
-- two key columns, which stay in the mart models. Keeping this ephemeral means
-- no extra object is created and the mart surface is unchanged.
with header as (
    select * from {{ ref('stg_sales_order_header') }}
),

detail as (
    select * from {{ ref('stg_sales_order_detail') }}
),

currency_rate as (
    select * from {{ ref('stg_currency_rate') }}
),

product_cost_history as (
    select * from {{ ref('stg_product_cost_history') }}
),

customer as (
    select * from {{ ref('stg_customer') }}
),

-- Reseller customers: the customer row that points at a store, keyed by store.
store_customer as (
    select
        customer_id as reseller_customer_id,
        store_id
    from customer
    where store_id is not null
      and person_id is null
),

order_lines as (
    select
        case when h.online_order_flag then 'internet' else 'reseller' end as channel,
        h.sales_order_id,
        h.order_date,
        h.due_date,
        h.ship_date,
        h.customer_id,
        h.sales_person_id,
        h.territory_id,
        h.sales_order_number,
        h.revision_number,
        h.purchase_order_number,
        h.tax_amt,
        h.freight,
        cr.to_currency_code as currency_code,
        d.product_id,
        d.special_offer_id,
        d.order_qty,
        d.unit_price,
        d.unit_price_discount,
        d.line_total,
        d.carrier_tracking_number,
        c.store_id as reseller_store_id,
        sc.reseller_customer_id,
        row_number() over (partition by h.sales_order_id order by d.sales_order_detail_id) as sales_order_line_number
    from header h
    inner join detail d on h.sales_order_id = d.sales_order_id
    -- LEFT, not INNER: an order whose customer row is missing should surface as
    -- an orphan key via the `relationships` test, not vanish from the fact.
    left join customer c on h.customer_id = c.customer_id
    left join store_customer sc on c.store_id = sc.store_id
    left join currency_rate cr on h.currency_rate_id = cr.currency_rate_id
),

-- Standard cost in effect on the order date: the latest history row that
-- starts on or before it.
product_cost as (
    select distinct on (product_id, order_date)
        product_id,
        order_date,
        standard_cost
    from (
        select
            ol.product_id,
            ol.order_date,
            pch.standard_cost,
            pch.start_date
        from order_lines ol
        join product_cost_history pch
            on ol.product_id = pch.product_id
            and pch.start_date <= ol.order_date
    ) sub
    order by product_id, order_date, start_date desc
),

final as (
    select
        ol.channel,
        ol.sales_order_id,
        ol.sales_order_line_number,
        ol.sales_order_number,
        ol.revision_number,
        ol.customer_id,
        ol.sales_person_id,
        ol.reseller_customer_id,
        ol.product_id,
        ol.special_offer_id,
        ol.territory_id,
        coalesce(ol.currency_code, 'USD') as currency_code,
        to_char(ol.order_date, 'YYYYMMDD')::int as order_date_key,
        to_char(ol.due_date, 'YYYYMMDD')::int as due_date_key,
        to_char(ol.ship_date, 'YYYYMMDD')::int as ship_date_key,
        ol.order_date,
        ol.due_date,
        ol.ship_date,
        ol.order_qty as order_quantity,
        ol.unit_price,
        ol.line_total as extended_amount,
        ol.line_total as sales_amount,
        ol.unit_price_discount * 100 as unit_price_discount_pct,
        (ol.unit_price * ol.order_qty * ol.unit_price_discount) as discount_amount,
        pc.standard_cost as product_standard_cost,
        (pc.standard_cost * ol.order_qty) as total_product_cost,
        ol.tax_amt,
        ol.freight,
        ol.carrier_tracking_number,
        ol.purchase_order_number as customer_po_number
    from order_lines ol
    left join product_cost pc
        on ol.product_id = pc.product_id
        and ol.order_date = pc.order_date
)

select * from final
