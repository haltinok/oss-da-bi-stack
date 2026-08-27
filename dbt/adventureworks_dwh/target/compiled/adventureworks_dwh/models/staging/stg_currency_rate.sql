with source as (
    select * from "analytics_2"."raw"."currency_rate"
),

renamed as (
    select
        currency_rate_id,
        currency_rate_date,
        from_currency_code,
        to_currency_code,
        average_rate,
        end_of_day_rate,
        modified_date
    from source
)

select * from renamed