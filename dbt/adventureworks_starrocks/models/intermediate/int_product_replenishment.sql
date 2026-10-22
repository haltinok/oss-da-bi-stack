{{ config(materialized='table', table_type='PRIMARY', keys=['product_id'], distributed_by=['product_id'], buckets=2) }}

-- How each product is replenished and what that costs in time and money.
-- A product with an active vendor row is `purchase` (lead time = the vendor's average lead time,
-- vendor chosen preferred-first then cheapest); otherwise a make_flag product is `manufacture`
-- (lead time = days_to_manufacture); otherwise `none` (never reordered). Lead time has a floor of 1 day.
with vendors as (
    select
        pv.product_id,
        pv.business_entity_id as vendor_id,
        v.name as vendor_name,
        pv.average_lead_time,
        pv.standard_price,
        pv.min_order_qty,
        pv.max_order_qty,
        row_number() over (
            partition by pv.product_id
            order by case when v.preferred_vendor_status then 0 else 1 end, pv.standard_price, pv.business_entity_id
        ) as pick
    from {{ ref('stg_product_vendor') }} pv
    inner join {{ ref('stg_vendor') }} v on v.business_entity_id = pv.business_entity_id
    where v.active_flag
),

best as (
    select * from vendors where pick = 1
)

select
    p.product_id,
    case
        when b.product_id is not null then 'purchase'
        when p.make_flag then 'manufacture'
        else 'none'
    end as replenishment_type,
    b.vendor_id,
    b.vendor_name,
    greatest(coalesce(case when b.product_id is not null then b.average_lead_time else p.days_to_manufacture end, 1), 1) as lead_time_days,
    b.min_order_qty,
    b.max_order_qty,
    coalesce(case when b.product_id is not null then b.standard_price end, p.standard_cost) as unit_cost
from {{ ref('stg_product') }} p
left join best b on b.product_id = p.product_id
