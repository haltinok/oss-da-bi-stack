with source as (
    select * from {{ source('adventureworks', 'country_region') }}
),

renamed as (
    select
        country_region_code,
        name,
        modified_date
    from source
)

select * from renamed
