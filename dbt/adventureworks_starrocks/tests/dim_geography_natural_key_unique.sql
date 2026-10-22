-- dim_geography's natural key must be unique: both dim_customer and dim_reseller
-- join to it on these four columns, so a single duplicate silently fans out
-- both dimensions. dbt's built-in generic tests cannot express a composite
-- uniqueness rule, and dbt_utils is not a dependency of this project, so this
-- is a singular test instead.
select
    city,
    state_province_code,
    country_region_code,
    postal_code,
    count(*) as row_count
from {{ ref('dim_geography') }}
group by city, state_province_code, country_region_code, postal_code
having count(*) > 1
