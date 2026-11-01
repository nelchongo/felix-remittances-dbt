-- Transaction fact, one row per payout attempt. Flags for first / retry / final attempts and for a
-- first attempt that failed but was rescued by a retry.
with

attempts as (
    select * from {{ ref('int_disbursements__attempts_ranked') }}
),

remittances as (
    select * from {{ ref('int_remittances__joined') }}
),

users as (
    select * from {{ ref('dim_users') }}
),

beneficiaries as (
    select * from {{ ref('dim_beneficiaries') }}
),

payout_providers as (
    select * from {{ ref('dim_payout_providers') }}
),

corridors as (
    select * from {{ ref('dim_corridors') }}
),

with_outcome as (
    select
        *,
        bool_or(is_final_attempt and is_completed) over (partition by receipt_id) as is_receipt_delivered
    from attempts
),

final as (
    select
        with_outcome.disbursement_id,
        with_outcome.receipt_id,
        coalesce(users.user_sk, '-1') as user_sk,
        coalesce(beneficiaries.beneficiary_sk, '-1') as beneficiary_sk,
        coalesce(payout_providers.payout_provider_sk, '-1') as payout_provider_sk,
        coalesce(corridors.corridor_sk, '-1') as corridor_sk,
        cast(strftime(with_outcome.attempted_at, '%Y%m%d') as integer) as attempted_date_sk,
        remittances.user_id,
        with_outcome.beneficiary_id,
        with_outcome.provider_name,
        with_outcome.payout_method,
        with_outcome.beneficiary_country as destination_country,
        with_outcome.attempt_number,
        with_outcome.final_status,
        with_outcome.failure_reason,
        with_outcome.attempted_at,
        with_outcome.resolved_at,
        remittances.send_amount_usd as payout_amount_usd,
        with_outcome.payout_amount_local,
        cast(with_outcome.minutes_to_resolve as bigint) as minutes_to_resolve,
        with_outcome.is_completed,
        with_outcome.is_failed,
        with_outcome.is_processing,
        with_outcome.is_first_attempt,
        with_outcome.is_retry,
        with_outcome.is_final_attempt,
        with_outcome.is_first_attempt and with_outcome.is_failed and with_outcome.is_receipt_delivered
            as is_rescued_by_retry
    from with_outcome
    left join remittances on with_outcome.receipt_id = remittances.receipt_id
    left join users
        on {{ scd2_point_in_time_join('users', 'remittances.user_id', 'user_id', 'with_outcome.attempted_at') }}
    left join beneficiaries
        on {{ scd2_point_in_time_join(
            'beneficiaries', 'with_outcome.beneficiary_id', 'beneficiary_id', 'with_outcome.attempted_at'
        ) }}
    left join payout_providers on with_outcome.provider_name = payout_providers.provider_name
    left join corridors on with_outcome.beneficiary_country = corridors.country_code
)

select * from final
