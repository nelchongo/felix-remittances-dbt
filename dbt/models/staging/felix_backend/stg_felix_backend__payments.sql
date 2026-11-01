-- One row per payment: its latest version (current status).
with

payment_events as (
    select * from {{ ref('stg_felix_backend__payment_events') }}
),

latest as (
    {{ dedupe_latest('payment_events', 'payment_id', 'updated_at desc nulls last, _loaded_at desc, _batch_id desc') }}
),

final as (
    select
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
    from latest
)

select * from final
