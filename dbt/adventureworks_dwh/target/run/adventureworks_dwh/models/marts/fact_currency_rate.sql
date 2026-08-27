
  
    

  create  table "analytics_2"."mart"."fact_currency_rate__dbt_tmp"
  
  
    as
  
  (
    with currency_rate as (
    select * from "analytics_2"."stage"."stg_currency_rate"
),

currency as (
    select * from "analytics_2"."stage"."stg_currency"
),

renamed as (
    select
        cr.to_currency_code as currency_key,
        to_char(cr.currency_rate_date, 'YYYYMMDD')::int as date_key,
        cr.currency_rate_date,
        cr.average_rate,
        cr.end_of_day_rate
    from currency_rate cr
    inner join currency c on cr.to_currency_code = c.currency_code
)

select * from renamed
  );
  