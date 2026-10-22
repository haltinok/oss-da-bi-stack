-- Which regions each user may see: the only table the auth service reads (as auth_ro, wildcard
-- SELECT on the `rls` schema granted once by starrocks/init.sh). Kept out of `mart` on purpose:
-- dbt drops and recreates mart tables on every build, and StarRocks drops table-level grants with
-- the table, which made logins fail during each build. Wildcard grants on a schema survive.
select
    u.username,
    t.sales_territory_region as region,
    t.sales_territory_group as grp
from {{ ref('dim_user_territory') }} u
inner join {{ ref('dim_sales_territory') }} t on t.sales_territory_key = u.sales_territory_key
