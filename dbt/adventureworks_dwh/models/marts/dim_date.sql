{{
    config(
        materialized='table'
    )
}}

with date_series as (
    select generate_series(
        '2010-01-01'::date,
        '2013-12-31'::date,
        interval '1 day'
    ) as date_day
),

renamed as (
    select
        to_char(date_day, 'YYYYMMDD')::int as date_key,
        date_day as full_date,
        extract(dow from date_day)::int + 1 as day_of_week,
        to_char(date_day, 'Day') as day_name,
        extract(day from date_day)::int as day_of_month,
        extract(doy from date_day)::int as day_of_year,
        extract(week from date_day)::int as week_of_year,
        to_char(date_day, 'Month') as month_name,
        extract(month from date_day)::int as month_of_year,
        extract(quarter from date_day)::int as calendar_quarter,
        extract(year from date_day)::int as calendar_year,
        case when extract(month from date_day) <= 6 then 1 else 2 end as calendar_semester,
        case
            when extract(month from date_day) between 7 and 9 then 1
            when extract(month from date_day) between 10 and 12 then 2
            when extract(month from date_day) between 1 and 3 then 3
            else 4
        end as fiscal_quarter,
        case when extract(month from date_day) >= 7 then extract(year from date_day)::int + 1 else extract(year from date_day)::int end as fiscal_year
    from date_series
)

select * from renamed
