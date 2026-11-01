-- One row per distinct payout attempt version (status change). Exact duplicate rows are removed.
with

source as (
    select * from {{ source('felix_backend', 'disbursements') }}
),

cleaned as (
    select
        trim(disbursement_id) as disbursement_id,
        trim(receipt_id) as receipt_id,
        try_cast(trim(attempt_number) as integer) as attempt_number,
        nullif(trim(provider_name), '') as provider_name,
        {{ normalize_enum('payout_method') }} as payout_method,
        trim(beneficiary_id) as beneficiary_id,
        nullif(trim(beneficiary_name), '') as beneficiary_name,
        upper(trim(beneficiary_country)) as beneficiary_country,
        nullif(trim(beneficiary_account_last4), '') as beneficiary_account_last4,
        {{ clean_amount('amount') }} as payout_amount_local,
        upper(trim(currency)) as payout_currency,
        {{ normalize_enum('status') }} as status,
        {{ normalize_enum('failure_reason') }} as failure_reason,
        {{ parse_timestamp('created_at') }} as created_at,
        {{ parse_timestamp('updated_at') }} as updated_at,
        _batch_id,
        _loaded_at
    from source
),

deduped as (
    {{ dedupe_latest('cleaned', 'disbursement_id, status, updated_at', '_loaded_at desc, _batch_id desc') }}
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['disbursement_id', 'status', 'updated_at']) }} as disbursement_event_id,
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
    from deduped
)

select * from final
