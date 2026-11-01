-- One row per distinct payment version (status change). Exact duplicate rows are removed.
-- Keeps the history that the latest-version model loses (a chargeback overwrites `succeeded`).
with

source as (
    select * from {{ source('felix_backend', 'payments') }}
),

cleaned as (
    select
        trim(payment_id) as payment_id,
        trim(user_id) as user_id,
        {{ clean_amount('amount') }} as send_amount_usd,
        {{ clean_amount('fee_amount') }} as fee_amount_usd,
        {{ clean_amount('store_fee_amount') }} as store_fee_amount_usd,
        upper(trim(currency)) as currency,
        {{ normalize_enum('payment_method') }} as payment_method,
        nullif(trim(payment_processor), '') as payment_processor,
        nullif(trim(funding_institution), '') as funding_institution,
        {{ normalize_enum('funding_institution_type') }} as funding_institution_type,
        nullif(trim(card_last4), '') as card_last4,
        {{ normalize_enum('status') }} as status,
        {{ normalize_enum('failure_reason') }} as failure_reason,
        {{ parse_timestamp('created_at') }} as created_at,
        {{ parse_timestamp('updated_at') }} as updated_at,
        _batch_id,
        _loaded_at
    from source
),

deduped as (
    {{ dedupe_latest('cleaned', 'payment_id, status, updated_at', '_loaded_at desc, _batch_id desc') }}
),

final as (
    select
        {{ dbt_utils.generate_surrogate_key(['payment_id', 'status', 'updated_at']) }} as payment_event_id,
        payment_id,
        user_id,
        send_amount_usd,
        fee_amount_usd,
        store_fee_amount_usd,
        currency,
        payment_method,
        payment_processor,
        funding_institution,
        funding_institution_type,
        card_last4,
        status,
        failure_reason,
        created_at,
        updated_at,
        _batch_id,
        _loaded_at
    from deduped
)

select * from final
