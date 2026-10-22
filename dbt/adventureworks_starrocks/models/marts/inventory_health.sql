{{ config(table_type='DUPLICATE', keys=['product_key'], distributed_by=['product_key'], buckets=2) }}

-- One row per product that is stocked, sold or on order: its stock position, a status, and what to do.
-- Thresholds are dbt vars (dbt_project.yml); all windows anchor on int_as_of_date.
--
-- status, first match wins:
--   discontinued  selling ended before the data's today (never reordered)
--   not_stocked   no inventory row anywhere and nothing on order (made to order or never stocked)
--   stockout      nothing on hand and there is demand
--   reorder_now   demand, and stock + what arrives within the lead time, less demand over the lead time,
--                 is at or below the safety stock (products with no way to replenish are never flagged)
--   dead_stock    stock on hand and no sale within dead_stock_days
--   overstock     cover above overstock_days of demand
--   healthy
with as_of as (
    select as_of_date from {{ ref('int_as_of_date') }}
),

base as (
    select
        p.product_id,
        p.name as product_name,
        p.make_flag,
        p.safety_stock_level,
        p.reorder_point,
        p.standard_cost,
        p.sell_end_date,
        s.on_hand,
        s.stocked_locations,
        s.on_order,
        r.replenishment_type,
        r.vendor_id,
        r.vendor_name,
        r.lead_time_days,
        r.min_order_qty,
        r.max_order_qty,
        r.unit_cost,
        d.last_sale_date,
        coalesce(
            case when coalesce(d.avg_daily_demand_28d, 0) > 0 then d.avg_daily_demand_28d end,
            d.avg_daily_demand_90d, 0
        ) as daily_demand,
        coalesce(due.on_order_in_lead_time, 0) as on_order_in_lead_time,
        a.as_of_date
    from {{ ref('stg_product') }} p
    inner join {{ ref('int_product_supply') }} s on s.product_id = p.product_id
    inner join {{ ref('int_product_replenishment') }} r on r.product_id = p.product_id
    left join {{ ref('int_product_demand') }} d on d.product_id = p.product_id
    cross join as_of a
    left join (
        select o.product_id, sum(o.open_qty) as on_order_in_lead_time
        from {{ ref('int_open_replenishment') }} o
        inner join {{ ref('int_product_replenishment') }} r2 on r2.product_id = o.product_id
        cross join as_of a2
        where o.due_date <= date_add(a2.as_of_date, interval r2.lead_time_days day)
        group by o.product_id
    ) due on due.product_id = p.product_id
    where s.stocked_locations > 0 or s.on_order > 0 or d.product_id is not null
),

scored as (
    select
        *,
        (on_hand + on_order) / nullif(daily_demand, 0) as days_of_cover,
        on_hand + on_order_in_lead_time - daily_demand * lead_time_days as projected_at_lead_time,
        daily_demand * {{ var('target_cover_days') }} as target_stock,
        -- AdventureWorks' stored safety stock / reorder point are static and unrelated to its sales
        -- (hundreds of units for a product that sells a few a day), so the safety stock used is capped at
        -- safety_stock_cap_days of demand. Reorder when the stock projected for the end of the lead time
        -- (on hand + what arrives within it - demand over it) is down to that safety stock.
        least(safety_stock_level, daily_demand * {{ var('safety_stock_cap_days') }}) as safety_stock_eff
    from base
),

classified as (
    select
        *,
        case
            when sell_end_date is not null and sell_end_date < as_of_date then 'discontinued'
            when stocked_locations = 0 and on_order = 0 then 'not_stocked'
            when on_hand = 0 and daily_demand > 0 then 'stockout'
            when replenishment_type <> 'none' and daily_demand > 0 and projected_at_lead_time <= safety_stock_eff then 'reorder_now'
            when on_hand > 0 and last_sale_date is null then 'dead_stock'
            when days_of_cover > {{ var('overstock_days') }} then 'overstock'
            else 'healthy'
        end as status
    from scored
),

sized as (
    select
        *,
        -- Reorder quantity: demand over lead time + review period, plus safety stock, less what is
        -- here or coming; at least the vendor minimum, at most the vendor maximum (purchased items).
        case
            when status in ('stockout', 'reorder_now') and replenishment_type <> 'none' then
                cast(
                    case when replenishment_type = 'purchase' then
                        least(
                            greatest(
                                greatest(ceil(daily_demand * (lead_time_days + {{ var('review_period_days') }}) + safety_stock_eff - on_hand - on_order), 0),
                                coalesce(min_order_qty, 0)
                            ),
                            case when coalesce(max_order_qty, 0) > 0 then max_order_qty else 9223372036854775807 end
                        )
                    else greatest(ceil(daily_demand * (lead_time_days + {{ var('review_period_days') }}) + safety_stock_eff - on_hand - on_order), 0)
                    end
                as bigint)
            else 0
        end as suggested_order_qty,
        case
            when status = 'overstock' then greatest(on_hand - target_stock, 0)
            when status = 'dead_stock' then cast(on_hand as double)
            else 0.0
        end as excess_units
    from classified
)

select
    product_id as product_key,
    product_name,
    status,
    replenishment_type,
    vendor_id,
    vendor_name,
    make_flag,
    on_hand,
    on_order,
    daily_demand,
    days_of_cover,
    lead_time_days,
    safety_stock_level,
    reorder_point,
    safety_stock_eff as safety_stock,
    projected_at_lead_time,
    last_sale_date,
    standard_cost,
    unit_cost,
    suggested_order_qty,
    suggested_order_qty * coalesce(unit_cost, 0) as suggested_order_value,
    target_stock,
    excess_units,
    excess_units * coalesce(standard_cost, 0) as excess_value,
    case
        when status = 'overstock' and excess_units < 2 * target_stock then 10
        when status = 'overstock' then 20
        when status = 'dead_stock' then 30
        else 0
    end as suggested_discount_pct,
    case status
        when 'stockout' then concat('Out of stock with ', cast(round(daily_demand, 1) as varchar), '/day demand, ', cast(lead_time_days as varchar), '-day lead time',
            case when suggested_order_qty > 0 then concat(' → order ', cast(suggested_order_qty as varchar))
                 when on_order > 0 then concat(', ', cast(on_order as varchar), ' already on order') else '' end)
        when 'reorder_now' then concat(cast(round(coalesce(days_of_cover, 0), 0) as varchar), ' days of cover, ', cast(lead_time_days as varchar), '-day lead time',
            case when replenishment_type = 'purchase' and coalesce(min_order_qty, 0) > 0 then concat(', vendor min ', cast(min_order_qty as varchar)) else '' end,
            ' → order ', cast(suggested_order_qty as varchar))
        when 'dead_stock' then concat('No sale in ', cast({{ var('dead_stock_days') }} as varchar), ' days, ', cast(on_hand as varchar), ' units on hand → discount ', cast(30 as varchar), '%')
        when 'overstock' then concat(cast(round(days_of_cover, 0) as varchar), ' days of cover vs target ', cast({{ var('target_cover_days') }} as varchar), ' → ',
            cast(round(excess_units, 0) as varchar), ' excess units, discount ', cast(case when excess_units < 2 * target_stock then 10 else 20 end as varchar), '%')
        when 'discontinued' then 'Selling has ended: not reordered'
        when 'not_stocked' then 'No inventory record: made to order or never stocked'
        else 'Within targets'
    end as reason
from sized
