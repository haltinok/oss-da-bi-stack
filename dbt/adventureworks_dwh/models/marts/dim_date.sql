-- Date spine for the star schema.
--
-- The bounds must cover every date key produced by the facts, otherwise the
-- values silently dangle (this dimension used to stop at 2013-12-31 while
-- AdventureWorks orders run to 2014-06-30, which left ~97k orphan fact rows).
-- Observed source domain:
--   sales orders          2011-05-31 .. 2014-06-30 (due/ship up to 2014-07-12)
--   product inventory     2008-03-31 .. 2014-08-12
--   currency rate / quota 2011-05-31 .. 2014-05-31
-- (source calendar; with the default `date_shift_years: 12` these land in
-- 2020-2026 in the mart -- see macros/shift_history_date.sql)
-- The source is now the live postgres_active sandbox, whose simulator stamps new
-- orders and inventory movements with `now()`, so the spine has to run past
-- today to keep those live date keys in range.
-- The `relationships` tests in _marts.yml fail loudly if a fact key lands
-- outside this window, so widening the source means widening this spine.
with date_series as (
    select generate_series(
        '2008-01-01'::date,
        -- The upper bound is relative to the build rather than a hardcoded year
        -- (it was '2040-12-31'). The spine only has to outrun the simulator's
        -- now() keys and the due/ship dates that trail a couple of weeks behind
        -- them, so two years of headroom is plenty, and a relative bound can't
        -- quietly expire the way a fixed one eventually does. It also drops
        -- ~4.5k rows that no fact or metric query ever reaches.
        -- This does NOT change what MetricFlow returns: a cumulative metric's
        -- horizon comes from its own grain_to_date/window and any offset_window
        -- on the metric, not from where the spine stops.
        -- Note the model is non-deterministic across builds by design -- the
        -- tail moves with the build date.
        (current_date + interval '2 years')::date,
        interval '1 day'
    ) as date_day
),

renamed as (
    select
        to_char(date_day, 'YYYYMMDD')::int as date_key,
        date_day as full_date,
        -- 1 = Sunday .. 7 = Saturday
        extract(dow from date_day)::int + 1 as day_of_week,
        -- trim(): to_char(..., 'Day')/'Month' are blank-padded to 9 characters
        trim(to_char(date_day, 'Day')) as day_name,
        extract(day from date_day)::int as day_of_month,
        extract(doy from date_day)::int as day_of_year,
        -- ISO-8601 week number
        extract(week from date_day)::int as week_of_year,
        trim(to_char(date_day, 'Month')) as month_name,
        extract(month from date_day)::int as month_of_year,
        extract(quarter from date_day)::int as calendar_quarter,
        extract(year from date_day)::int as calendar_year,
        case when extract(month from date_day) <= 6 then 1 else 2 end as calendar_semester,
        -- AdventureWorks runs a July-June fiscal year.
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
