{{ config(materialized='table', table_type='PRIMARY', keys=['product_id'], distributed_by=['product_id'], buckets=4) }}

-- Units sold per product over the trailing 28 and 90 days (internet + reseller, rejected and cancelled
-- orders left out), anchored on the data's own latest order date (int_as_of_date), never on today. This is
-- the only inventory model that scans the facts: it reads just the trailing window.
-- A product with no sale in the window has no row. The window is the longer of 90 days and the
-- dead-stock horizon, so "no sale in dead_stock_days" is simply "no last_sale_date".
with as_of as (
    select as_of_date from {{ ref('int_as_of_date') }}
),

lines as (
    select product_key as product_id, order_date, order_quantity
    from {{ ref('fact_internet_sales') }}
    where order_status not in (4, 6)
    union all
    select product_key as product_id, order_date, order_quantity
    from {{ ref('fact_reseller_sales') }}
    where order_status not in (4, 6)
)

select
    l.product_id,
    sum(case when l.order_date > date_sub(a.as_of_date, interval 28 day) then l.order_quantity else 0 end) as units_28d,
    sum(case when l.order_date > date_sub(a.as_of_date, interval 90 day) then l.order_quantity else 0 end) as units_90d,
    sum(case when l.order_date > date_sub(a.as_of_date, interval 28 day) then l.order_quantity else 0 end) / 28.0 as avg_daily_demand_28d,
    sum(case when l.order_date > date_sub(a.as_of_date, interval 90 day) then l.order_quantity else 0 end) / 90.0 as avg_daily_demand_90d,
    max(l.order_date) as last_sale_date
from lines l
cross join as_of a
where l.order_date > date_sub(a.as_of_date, interval {{ [90, var('dead_stock_days') | int] | max }} day)
  and l.order_date <= a.as_of_date
group by l.product_id
