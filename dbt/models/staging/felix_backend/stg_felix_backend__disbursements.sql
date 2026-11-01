-- One row per payout attempt: its latest version (current status).
with

disbursement_events as (
    select * from {{ ref('stg_felix_backend__disbursement_events') }}
),

latest as (
    {{ dedupe_latest(
        'disbursement_events', 'disbursement_id', 'updated_at desc nulls last, _loaded_at desc, _batch_id desc'
    ) }}
),

final as (
    select
        disbursement_id,
        receipt_id,
        attempt_number,
        provider_name,
        payout_method,
        beneficiary_id,
        beneficiary_name,
        beneficiary_country,
        beneficiary_account_last4,
        payout_amount_local,
        payout_currency,
        status,
        failure_reason,
        created_at,
        updated_at,
        _batch_id,
        _loaded_at
    from latest
)

select * from final
