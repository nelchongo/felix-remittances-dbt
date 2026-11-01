-- One row per user: the latest profile version. History is kept by the snp_users snapshot.
with

source as (
    select * from {{ source('felix_backend', 'users') }}
),

cleaned as (
    select
        trim(user_id) as user_id,
        nullif(trim(first_name), '') as first_name,
        nullif(trim(last_name), '') as last_name,
        nullif(lower(trim(email)), '') as email,
        nullif(trim(phone_number), '') as phone_number,
        upper(trim(country)) as country,
        upper(trim(state)) as state,
        {{ normalize_enum('kyc_status') }} as kyc_status,
        {{ parse_timestamp('created_at') }} as created_at,
        {{ parse_timestamp('updated_at') }} as updated_at,
        _batch_id,
        _loaded_at
    from source
),

latest as (
    {{ dedupe_latest('cleaned', 'user_id', 'updated_at desc nulls last, _loaded_at desc, _batch_id desc') }}
),

final as (
    select
        user_id,
        first_name,
        last_name,
        email,
        phone_number,
        country,
        state,
        kyc_status,
        created_at,
        updated_at,
        _batch_id,
        _loaded_at
    from latest
)

select * from final
