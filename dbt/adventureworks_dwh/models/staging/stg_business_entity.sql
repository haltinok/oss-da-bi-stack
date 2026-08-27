with source as (
    select * from {{ source('adventureworks', 'business_entity') }}
),

renamed as (
    select
        business_entity_id,
        rowguid,
        modified_date
    from source
)

select * from renamed
