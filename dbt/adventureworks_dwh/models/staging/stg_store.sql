with source as (
    select * from {{ source('adventureworks', 'store') }}
),

renamed as (
    select
        business_entity_id,
        name,
        sales_person_id,
        demographics,
        rowguid,
        modified_date
    from source
)

select * from renamed
