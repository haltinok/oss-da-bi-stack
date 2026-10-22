{{ config(
    materialized='incremental',
    unique_key=['product_id', 'valid_from'],
    distributed_by=['product_id'],
    buckets=2,
) }}

-- Append-only product version log: one row each time a product's modified_date
-- advances. This replaces `dbt snapshot` on StarRocks: dbt-starrocks' snapshot
-- merge issues a MySQL multi-table UPDATE that StarRocks rejects, and its
-- snapshot table is a duplicate-key table that cannot be updated. Insert-only
-- needs neither; validity windows are derived in dim_product_history.
-- Primary-key table, so re-running the same version is an idempotent upsert.
select
    s.product_id,
    s.modified_date as valid_from,
    s.name as product_name,
    s.product_number,
    s.list_price,
    s.standard_cost
from {{ ref('stg_product') }} s
{% if is_incremental() %}
left join (
    select product_id, max(valid_from) as last_valid_from
    from {{ this }}
    group by product_id
) t on t.product_id = s.product_id
where t.last_valid_from is null or s.modified_date > t.last_valid_from
{% endif %}
