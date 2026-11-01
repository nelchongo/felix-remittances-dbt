-- Q4 label. One row per payout provider: attempt counts and `reliability_tier` from the attempt failure
-- share (thresholds in var('provider_failure_tiers')). Providers with fewer than
-- var('provider_min_attempts') attempts are `insufficient_data`. The share itself is not stored: the
-- metric `payout_attempt_failure_rate` lives in the semantic layer.
with

attempts as (
    select * from {{ ref('int_disbursements__attempts_ranked') }}
),

providers as (
    select
        provider_name,
        count(*) as n_attempts,
        count(*) filter (where is_failed) as n_failed_attempts,
        count(*) filter (where is_completed) as n_completed_attempts
    from attempts
    where provider_name is not null
    group by provider_name
),

final as (
    select
        provider_name,
        cast(n_attempts as integer) as n_attempts,
        cast(n_failed_attempts as integer) as n_failed_attempts,
        cast(n_completed_attempts as integer) as n_completed_attempts,
        case
            when n_attempts < {{ var('provider_min_attempts') }} then 'insufficient_data'
            else {{ classify_tier(safe_divide('n_failed_attempts', 'n_attempts'), 'provider_failure_tiers', 'critical') }}
        end as reliability_tier
    from providers
)

select * from final
