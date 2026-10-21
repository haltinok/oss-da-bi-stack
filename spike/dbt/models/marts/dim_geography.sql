{{ config(table_type='PRIMARY', keys=['geography_key'], distributed_by=['geography_key'], buckets=2) }}

with address as (
    select * from {{ ref('stg_address') }}
),

state_province as (
    select * from {{ ref('stg_state_province') }}
),

country_region as (
    select * from {{ ref('stg_country_region') }}
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
)

-- Deterministic hash of the natural key (stable across rebuilds), as in the
-- Postgres project: first 60 bits of the md5 as a bigint.
select
    cast(conv(substr(md5(concat_ws('|', city, state_province_code, country_region_code, postal_code)), 1, 15), 16, 10) as bigint) as geography_key,
    city,
    state_province_code,
    state_province_name,
    country_region_code,
    country_region_name,
    postal_code,
    sales_territory_key
from geography_keys
