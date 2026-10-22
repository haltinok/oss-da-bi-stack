{{ config(table_type='DUPLICATE', keys=['special_offer_id'], distributed_by=['special_offer_id'], buckets=1) }}

-- Descriptive evidence for campaign suggestions: for each discount offer, how fast the products that sold
-- under it moved during the offer compared with the 28 days before it. Not an elasticity model, and with
-- no control group it also picks up seasonality and trend, so read the lift as "what happened", not "what
-- the discount caused". Products = those that had at least one line sold under the offer. Windows clip at
-- the data's newest order (int_as_of_date). `lift` is null when there is no baseline (the offer started
-- before the data did, or its products did not sell in the 28 days before).
with as_of as (
    select as_of_date from {{ ref('int_as_of_date') }}
),

offers as (
    select
        o.special_offer_id,
        o.description,
        o.type as offer_type,
        o.category as offer_category,
        o.discount_pct,
        o.start_date,
        least(o.end_date, a.as_of_date) as end_date
    from {{ ref('stg_special_offer') }} o
    cross join as_of a
    where o.discount_pct > 0
      and o.start_date <= a.as_of_date
),

lines as (
    select product_key, order_date, order_quantity, promotion_key
    from {{ ref('fact_internet_sales') }}
    where order_status not in (4, 6)
    union all
    select product_key, order_date, order_quantity, promotion_key
    from {{ ref('fact_reseller_sales') }}
    where order_status not in (4, 6)
),

offer_products as (
    select distinct l.promotion_key as special_offer_id, l.product_key
    from lines l
    inner join offers o on o.special_offer_id = l.promotion_key
),

measured as (
    select
        o.special_offer_id,
        sum(case when l.order_date >= o.start_date and l.order_date < date_add(o.end_date, interval 1 day) then l.order_quantity else 0 end) as units_during,
        sum(case when l.order_date >= date_sub(o.start_date, interval 28 day) and l.order_date < o.start_date then l.order_quantity else 0 end) as units_before,
        sum(case when l.order_date >= o.start_date and l.order_date < date_add(o.end_date, interval 1 day) and l.promotion_key = o.special_offer_id then l.order_quantity else 0 end) as units_with_offer
    from offers o
    inner join offer_products p on p.special_offer_id = o.special_offer_id
    inner join lines l on l.product_key = p.product_key
        and l.order_date >= date_sub(o.start_date, interval 28 day)
        and l.order_date < date_add(o.end_date, interval 1 day)
    group by o.special_offer_id
)

select
    o.special_offer_id,
    o.description,
    o.offer_type,
    o.offer_category,
    o.discount_pct,
    case
        when o.discount_pct <= 0.10 then '1-10%'
        when o.discount_pct <= 0.20 then '11-20%'
        when o.discount_pct <= 0.30 then '21-30%'
        else 'over 30%'
    end as discount_band,
    o.start_date,
    o.end_date,
    datediff(o.end_date, o.start_date) + 1 as days_during,
    coalesce(m.units_during, 0) as units_during,
    coalesce(m.units_with_offer, 0) as units_with_offer,
    coalesce(m.units_before, 0) as units_before,
    coalesce(m.units_during, 0) / (datediff(o.end_date, o.start_date) + 1) as units_per_day_during,
    coalesce(m.units_before, 0) / 28.0 as units_per_day_before,
    case
        when coalesce(m.units_before, 0) > 0 then (coalesce(m.units_during, 0) / (datediff(o.end_date, o.start_date) + 1)) / (m.units_before / 28.0)
    end as lift
from offers o
left join measured m on m.special_offer_id = o.special_offer_id
