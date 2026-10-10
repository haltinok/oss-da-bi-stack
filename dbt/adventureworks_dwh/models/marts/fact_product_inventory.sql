-- Product inventory snapshot by stocking location.
-- Grain: one row per (product_key, location_key).
--
-- NOTE: `movement_date` is AdventureWorks' `modified_date` -- when the source
-- row last changed (observed 2008-03-31 .. 2014-08-12), not a load/snapshot
-- date. If you need true as-of semantics, stamp the dlt load timestamp here
-- instead of the source modification date. Historical values are moved
-- forward by `date_shift_years` like the other business dates
-- (macros/shift_history_date.sql); staging keeps the raw audit column.
with inventory as (
    select * from {{ ref('stg_product_inventory') }}
),

renamed as (
    select
        product_id as product_key,
        location_id as location_key,
        to_char({{ shift_history_date('modified_date') }}, 'YYYYMMDD')::int as date_key,
        {{ shift_history_date('modified_date') }} as movement_date,
        quantity as units_balance
    from inventory
)

select * from renamed
