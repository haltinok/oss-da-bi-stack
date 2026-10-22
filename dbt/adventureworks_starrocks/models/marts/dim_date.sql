{{ config(table_type='PRIMARY', keys=['date_key'], distributed_by=['date_key'], buckets=1) }}

-- Date spine for the star schema, 2008-01-01 .. 2040-12-31 inclusive (same bounds as the
-- Postgres project). The scaled spike data runs 2011-2021 (due/ship dates a few
-- weeks past the last order), so every fact date key lands inside it.
with date_series as (
    select date_add(cast('2008-01-01' as date), interval n day) as date_day
    from (select generate_series as n from table(generate_series(0, 12053))) s
),

renamed as (
    select
        cast(date_format(date_day, '%Y%m%d') as int) as date_key,
        date_day as full_date,
        -- 1 = Sunday .. 7 = Saturday
        dayofweek(date_day) as day_of_week,
        dayname(date_day) as day_name,
        dayofmonth(date_day) as day_of_month,
        dayofyear(date_day) as day_of_year,
        -- ISO-8601 week number
        weekofyear(date_day) as week_of_year,
        monthname(date_day) as month_name,
        month(date_day) as month_of_year,
        quarter(date_day) as calendar_quarter,
        year(date_day) as calendar_year,
        case when month(date_day) <= 6 then 1 else 2 end as calendar_semester,
        -- AdventureWorks runs a July-June fiscal year.
        case
            when month(date_day) between 7 and 9 then 1
            when month(date_day) between 10 and 12 then 2
            when month(date_day) between 1 and 3 then 3
            else 4
        end as fiscal_quarter,
        case when month(date_day) >= 7 then year(date_day) + 1 else year(date_day) end as fiscal_year
    from date_series
)

select * from renamed
