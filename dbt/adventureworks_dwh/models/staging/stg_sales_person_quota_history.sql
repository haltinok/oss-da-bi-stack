with source as (
    select * from {{ source('adventureworks', 'sales_person_quota_history') }}
),

renamed as (
    select
        business_entity_id,
        {{ shift_history_date('quota_date') }} as quota_date,
        sales_quota,
        rowguid,
        modified_date
    from source
)

select * from renamed
