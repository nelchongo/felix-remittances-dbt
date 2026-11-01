-- One row per payout attempt, ranked within its receipt, with resolution timestamps and flags.
with

disbursements as (
    select * from {{ ref('stg_felix_backend__disbursements') }}
),

disbursement_events as (
    select * from {{ ref('stg_felix_backend__disbursement_events') }}
),

resolutions as (
    select
        disbursement_id,
        min(updated_at) filter (where status = 'completed') as completed_at,
        min(updated_at) filter (where status = 'failed') as failed_at
    from disbursement_events
    group by disbursement_id
),

ranked as (
    select
        disbursements.disbursement_id,
        disbursements.receipt_id,
        disbursements.attempt_number,
        disbursements.provider_name,
        disbursements.payout_method,
        disbursements.beneficiary_id,
        disbursements.beneficiary_country,
        disbursements.payout_amount_local,
        disbursements.payout_currency,
        disbursements.status as final_status,
        disbursements.failure_reason,
        disbursements.created_at as attempted_at,
        resolutions.completed_at,
        resolutions.failed_at,
        coalesce(resolutions.completed_at, resolutions.failed_at) as resolved_at,
        row_number() over (
            partition by disbursements.receipt_id order by disbursements.attempt_number desc
        ) = 1 as is_final_attempt
    from disbursements
    left join resolutions on disbursements.disbursement_id = resolutions.disbursement_id
),

final as (
    select
        disbursement_id,
        receipt_id,
        attempt_number,
        provider_name,
        payout_method,
        beneficiary_id,
        beneficiary_country,
        payout_amount_local,
        payout_currency,
        final_status,
        failure_reason,
        attempted_at,
        completed_at,
        failed_at,
        resolved_at,
        date_diff('minute', attempted_at, resolved_at) as minutes_to_resolve,
        attempt_number = 1 as is_first_attempt,
        is_final_attempt,
        attempt_number > 1 as is_retry,
        final_status = 'completed' as is_completed,
        final_status = 'failed' as is_failed,
        final_status = 'processing' as is_processing
    from ranked
)

select * from final
