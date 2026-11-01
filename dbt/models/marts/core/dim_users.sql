-- Sender dimension. Type 2 (from snp_users): kyc_status, state. Type 1 (current value on every version):
-- masked email and phone, and the classification labels. First version opens at 1900-01-01 so events
-- before the first captured change still find a version. Unknown member: user_sk = '-1'.
with

snapshot as (
    select * from {{ ref('snp_users') }}
),

current_profile as (
    select * from {{ ref('stg_felix_backend__users') }}
),

versions as (
    select
        snapshot.dbt_scd_id as user_sk,
        snapshot.user_id,
        snapshot.country,
        snapshot.state,
        snapshot.kyc_status,
        snapshot.created_at as signed_up_at,
        snapshot.dbt_valid_from,
        snapshot.dbt_valid_to,
        row_number() over (partition by snapshot.user_id order by snapshot.dbt_valid_from) as version_number
    from snapshot
),

final as (
    select
        versions.user_sk,
        versions.user_id,
        cast(versions.version_number as integer) as version_number,
        {{ mask_pii('current_profile.email', 'email') }} as email_masked,
        {{ mask_pii('current_profile.phone_number', 'phone') }} as phone_masked,
        versions.country,
        versions.state,
        versions.kyc_status,
        versions.signed_up_at,
        -- Type 1 labels, filled in Phase 5 from the label models
        cast(null as varchar) as volume_segment,
        cast(null as integer) as volume_rank,
        cast(null as varchar) as cluster_id,
        cast(null as varchar) as primary_payment_method,
        cast(null as date) as first_transfer_month,
        case
            when versions.version_number = 1 then cast('1900-01-01' as timestamp) else versions.dbt_valid_from
        end as valid_from,
        versions.dbt_valid_to as valid_to,
        versions.dbt_valid_to = cast('9999-12-31' as timestamp) as is_current
    from versions
    left join current_profile on versions.user_id = current_profile.user_id
)

select * from final
union all by name
{{ unknown_member(model.columns, {
    'user_id': "'unknown'",
    'valid_from': "cast('1900-01-01' as timestamp)",
    'valid_to': "cast('9999-12-31' as timestamp)",
    'is_current': 'true',
}) }}
