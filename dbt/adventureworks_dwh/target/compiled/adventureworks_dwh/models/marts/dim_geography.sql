with address as (
    select * from "analytics_2"."stage"."stg_address"
),

state_province as (
    select * from "analytics_2"."stage"."stg_state_province"
),

country_region as (
    select * from "analytics_2"."stage"."stg_country_region"
),

sales_territory as (
    select * from "analytics_2"."stage"."stg_sales_territory"
),

geography_keys as (
    select distinct
        a.city,
        sp.state_province_code,
        sp.name as state_province_name,
        sp.country_region_code,
        cr.name as country_region_name,
        a.postal_code,
        sp.territory_id as sales_territory_key
    from address a
    inner join state_province sp on a.state_province_id = sp.state_province_id
    inner join country_region cr on sp.country_region_code = cr.country_region_code
),

numbered as (
    select
        row_number() over (
            order by city, state_province_code, country_region_code, postal_code
        ) as geography_key,
        city,
        state_province_code,
        state_province_name,
        country_region_code,
        country_region_name,
        postal_code,
        sales_territory_key
    from geography_keys
)

select * from numbered