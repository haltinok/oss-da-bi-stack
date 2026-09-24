with customer as (
    select * from {{ ref('stg_customer') }}
),

person as (
    select * from {{ ref('stg_person') }}
),

email as (
    select distinct on (business_entity_id)
        business_entity_id,
        email_address
    from {{ ref('stg_email_address') }}
    order by business_entity_id, email_address_id
),

address as (
    select * from {{ ref('stg_address') }}
),

business_entity_address as (
    select * from {{ ref('stg_business_entity_address') }}
),

state_province as (
    select * from {{ ref('stg_state_province') }}
),

dim_geography as (
    select * from {{ ref('dim_geography') }}
),

-- Individual customers only; reseller (store) customers are in dim_reseller.
customer_person as (
    select
        c.customer_id,
        c.person_id,
        p.title,
        p.first_name,
        p.middle_name,
        p.last_name,
        p.suffix,
        p.name_style
    from customer c
    inner join person p on c.person_id = p.business_entity_id
    where c.store_id is null
),

-- AdventureWorks address_type_id: 1 Billing, 2 Home, 3 Main Office,
-- 4 Primary, 5 Shipping, 6 Archive. An individual resolves to their Home
-- address; ties broken by the lowest address_id for determinism.
customer_address as (
    select distinct on (bea.business_entity_id)
        bea.business_entity_id,
        a.city,
        sp.state_province_code,
        sp.country_region_code,
        a.postal_code
    from business_entity_address bea
    inner join address a on bea.address_id = a.address_id
    inner join state_province sp on a.state_province_id = sp.state_province_id
    where bea.address_type_id = 2
    order by bea.business_entity_id, bea.address_id
)

select
    cp.customer_id as customer_key,
    cp.customer_id as customer_alternate_key,
    cp.title,
    cp.first_name,
    cp.middle_name,
    cp.last_name,
    cp.suffix,
    cp.name_style,
    e.email_address,
    dg.geography_key
from customer_person cp
left join email e on cp.person_id = e.business_entity_id
left join customer_address ca on cp.person_id = ca.business_entity_id
left join dim_geography dg
    on dg.city = ca.city
    and dg.state_province_code = ca.state_province_code
    and dg.country_region_code = ca.country_region_code
    and dg.postal_code = ca.postal_code
