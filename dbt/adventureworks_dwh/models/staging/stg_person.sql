with source as (
    select * from {{ source('adventureworks', 'person') }}
),

renamed as (
    select
        business_entity_id,
        person_type,
        name_style,
        title,
        first_name,
        middle_name,
        last_name,
        suffix,
        email_promotion,
        additional_contact_info,
        demographics,
        rowguid,
        modified_date
    from source
)

select * from renamed
