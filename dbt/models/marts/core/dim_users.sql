-- Sender dimension. Type 2 (from snp_users): kyc_status, state.
-- Type 1 (current value on every version): masked email and phone, and the classification labels
-- (Q2 volume segment, Q5 cluster). The first version opens at 1900-01-01 so events before the first
-- captured change still find a version. Unknown member: user_sk = '-1'.
with

snapshot as (
    select * from {{ ref('snp_users') }}
),

current_profile as (
    select * from {{ ref('stg_felix_backend__users') }}
),

volume_ranking as (
    select * from {{ ref('int_customers__volume_ranking') }}
),

clusters as (
    select * from {{ ref('int_customers__sender_graph_components') }}
),

payments as (
    select * from {{ ref('int_payments__lifecycle') }}
),

sender_profile as (
    select
        user_id,
        cast(date_trunc('month', min(succeeded_at)) as date) as first_transfer_month,
        mode(payment_method order by payment_method) as primary_payment_method
    from payments
    where is_succeeded
    group by user_id
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
        -- Type 1 labels (same value on every version). Users without a succeeded transfer get 'no_transfers'.
        coalesce(volume_ranking.volume_segment, 'no_transfers') as volume_segment,
        volume_ranking.volume_rank,
        clusters.cluster_id,
        coalesce(clusters.cluster_type, 'no_transfers') as cluster_type,
        sender_profile.primary_payment_method,
        sender_profile.first_transfer_month,
        case
            when versions.version_number = 1 then cast('1900-01-01' as timestamp) else versions.dbt_valid_from
        end as valid_from,
        versions.dbt_valid_to as valid_to,
        versions.dbt_valid_to = cast('9999-12-31' as timestamp) as is_current
    from versions
    left join current_profile on versions.user_id = current_profile.user_id
    left join volume_ranking on versions.user_id = volume_ranking.user_id
    left join clusters on versions.user_id = clusters.user_id
    left join sender_profile on versions.user_id = sender_profile.user_id
)

select * from final
union all by name
{{ unknown_member(model.columns, {
    'user_id': "'unknown'",
    'valid_from': "cast('1900-01-01' as timestamp)",
    'valid_to': "cast('9999-12-31' as timestamp)",
    'is_current': 'true',
}) }}
