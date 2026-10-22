with source as (
    select * from {{ source('adventureworks', 'state_province') }}
),

renamed as (
    select
        state_province_id,
        state_province_code,
        country_region_code,
        is_only_state_province_flag,
        name,
        territory_id,
        rowguid,
        modified_date
    from source
)

select * from renamed
