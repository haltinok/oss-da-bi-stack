with quota_history as (
    select * from "analytics_2"."stage"."stg_sales_person_quota_history"
),

renamed as (
    select
        business_entity_id as employee_key,
        to_char(quota_date, 'YYYYMMDD')::int as date_key,
        quota_date,
        extract(year from quota_date)::int as calendar_year,
        extract(quarter from quota_date)::int as calendar_quarter,
        sales_quota as sales_amount_quota
    from quota_history
)

select * from renamed