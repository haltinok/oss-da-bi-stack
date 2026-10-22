{{ config(materialized='table', buckets=1) }}

-- The data's "today": the newest order date across both facts. Every inventory window (trailing 28/90
-- days, "no sales in 90 days", "due within the lead time") anchors on this and never on current_date,
-- because a scaled benchmark schema ends in the past while the live sandbox keeps moving forward.
select max(order_date) as as_of_date
from (
    select max(order_date) as order_date from {{ ref('fact_internet_sales') }}
    union all
    select max(order_date) as order_date from {{ ref('fact_reseller_sales') }}
) f
