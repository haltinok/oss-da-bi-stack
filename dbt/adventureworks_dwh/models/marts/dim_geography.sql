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
),

-- The surrogate key is a deterministic hash of the natural key, NOT row_number().
-- dlt reloads the raw layer with `write_disposition="replace"`, so an
-- order-dependent key gets re-minted whenever a single new address happens to
-- sort earlier in the window (measured: adding one such row shifted all 683 keys).
-- A hash stays stable across rebuilds and keeps the column type numeric.
keyed as (
    select
        ('x' || substr(md5(
            city || '|' || state_province_code || '|' || country_region_code || '|' || postal_code
        ), 1, 15))::bit(60)::bigint as geography_key,
        city,
        state_province_code,
        state_province_name,
        country_region_code,
        country_region_name,
        postal_code,
        sales_territory_key
    from geography_keys
)

select * from keyed
