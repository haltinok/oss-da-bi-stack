{% snapshot dim_product_snapshot %}
{{
    config(
        target_schema='snapshots',
        unique_key='product_id',
        strategy='timestamp',
        updated_at='modified_date',
        invalidate_hard_deletes=True,
    )
}}

-- Type 2 history for product. The simulator changes list_price every 5 minutes,
-- and dim_product is rebuilt as Type 1 (it keeps only the current value), so this
-- snapshot is where the price history lives. `dbt build` runs it with the models.
select * from {{ source('adventureworks', 'product') }}

{% endsnapshot %}
