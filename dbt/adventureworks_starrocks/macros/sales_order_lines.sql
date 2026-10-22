{#-
  Per-order-line grain shared by fact_internet_sales and fact_reseller_sales. A macro rather
  than an ephemeral model so that is_incremental() is evaluated in the calling fact.

  Incremental runs only rebuild the orders touched since the fact's own watermark, so the
  line-number window and the joins scan a few orders instead of every line. The upsert is
  keyed on the line, so the lookback overlap is harmless.
-#}
{% macro incremental_orders_filter(which) %}
    {% if is_incremental() %}
    where sales_order_id in (
        select sales_order_id from {{ ref('stg_sales_order_header') }}
        where modified_date >= {{ incremental_watermark() }}
        union
        select sales_order_id from {{ ref('stg_sales_order_detail') }}
        where modified_date >= {{ incremental_watermark() }}
    )
    {% endif %}
{% endmacro %}

{% macro incremental_watermark() -%}
    (select date_sub(coalesce(max(source_modified_date), '1970-01-01'), interval {{ var('incremental_lookback_minutes', 60) }} minute) from {{ this }})
{%- endmacro %}

{% macro sales_order_lines(channel) %}
with header as (
    select * from {{ ref('stg_sales_order_header') }}
    {{ incremental_orders_filter('header') }}
),

detail as (
    select * from {{ ref('stg_sales_order_detail') }}
    {{ incremental_orders_filter('detail') }}
),

-- The line number is numbered over the two key columns only. Numbering it inside
-- order_lines puts every joined column through the window, which ran StarRocks
-- out of memory (27 GB) at 10M lines.
line_numbers as (
    select
        sales_order_id,
        sales_order_detail_id,
        row_number() over (partition by sales_order_id order by sales_order_detail_id) as sales_order_line_number
    from detail
),

currency_rate as (
    select * from {{ ref('stg_currency_rate') }}
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
        case when h.online_order_flag = 1 then 'internet' else 'reseller' end as channel,
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
        h.status as order_status,
        greatest(h.modified_date, d.modified_date) as source_modified_date,
        h.sub_total,
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
        ln.sales_order_line_number
    from header h
    inner join detail d on h.sales_order_id = d.sales_order_id
    inner join line_numbers ln
        on ln.sales_order_id = d.sales_order_id
        and ln.sales_order_detail_id = d.sales_order_detail_id
    -- LEFT, not INNER: an order whose customer row is missing should surface as
    -- an orphan key via the `relationships` test, not vanish from the fact.
    left join customer c on h.customer_id = c.customer_id
    left join store_customer sc on c.store_id = sc.store_id
    left join currency_rate cr on h.currency_rate_id = cr.currency_rate_id
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
        cast(date_format(ol.order_date, '%Y%m%d') as int) as order_date_key,
        cast(date_format(ol.due_date, '%Y%m%d') as int) as due_date_key,
        cast(date_format(ol.ship_date, '%Y%m%d') as int) as ship_date_key,
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
        ol.order_status,
        ol.source_modified_date,
        -- Header-level tax/freight are allocated across the order's lines by share
        -- of sub_total, so SUM() over the fact matches the order. Previously the
        -- full header amount was copied onto every line, overstating the total by
        -- roughly the average number of lines per order (~25x on the seed).
        ol.tax_amt * ol.line_total / nullif(ol.sub_total, 0) as tax_amt,
        ol.freight * ol.line_total / nullif(ol.sub_total, 0) as freight,
        ol.carrier_tracking_number,
        ol.purchase_order_number as customer_po_number
    from order_lines ol
    left join {{ ref('product_cost_daily') }} pc
        on ol.product_id = pc.product_id
        and ol.order_date = pc.order_date
)

select * from final
where channel = '{{ channel }}'
{% endmacro %}

{# A merge load never sees deleted orders. Drop fact rows whose order is gone from staging
   (which already anti-joins the PK snapshot when use_pk_snapshots is on). #}
{% macro delete_removed_orders() %}
    {% if is_incremental() %}
    delete from {{ this }} where sales_order_number not in (select sales_order_number from {{ ref('stg_sales_order_header') }})
    {% endif %}
{% endmacro %}
