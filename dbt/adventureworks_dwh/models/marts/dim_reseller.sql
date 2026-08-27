with store as (
    select * from {{ ref('stg_store') }}
),

customer as (
    select * from {{ ref('stg_customer') }}
),

business_entity_address as (
    select * from {{ ref('stg_business_entity_address') }}
),

address as (
    select * from {{ ref('stg_address') }}
),

state_province as (
    select * from {{ ref('stg_state_province') }}
),

country_region as (
    select * from {{ ref('stg_country_region') }}
),

dim_geography as (
    select * from {{ ref('dim_geography') }}
),

store_customer as (
    select
        customer_id,
        store_id,
        territory_id,
        account_number
    from customer
    where store_id is not null
      and person_id is null
),

store_address as (
    select distinct on (bea.business_entity_id)
        bea.business_entity_id,
        a.city,
        sp.state_province_code,
        sp.country_region_code,
        a.postal_code
    from business_entity_address bea
    inner join address a on bea.address_id = a.address_id
    inner join state_province sp on a.state_province_id = sp.state_province_id
    order by bea.business_entity_id, bea.address_id
)

select
    sc.customer_id as reseller_key,
    sc.account_number as reseller_alternate_key,
    s.name as reseller_name,
    s.sales_person_id,
    sc.territory_id as sales_territory_key,
    dg.geography_key
from store s
inner join store_customer sc on s.business_entity_id = sc.store_id
left join store_address sa on s.business_entity_id = sa.business_entity_id
left join dim_geography dg
    on dg.city = sa.city
    and dg.state_province_code = sa.state_province_code
    and dg.country_region_code = sa.country_region_code
    and dg.postal_code = sa.postal_code
