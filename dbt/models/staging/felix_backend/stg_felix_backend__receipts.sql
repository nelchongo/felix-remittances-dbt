-- One row per receipt (one per successful payment). Receipts are immutable: only exact duplicates are removed.
with

source as (
    select * from {{ source('felix_backend', 'receipts') }}
),

cleaned as (
    select
        trim(receipt_id) as receipt_id,
        trim(payment_id) as payment_id,
        trim(user_id) as user_id,
        trim(beneficiary_id) as beneficiary_id,
        {{ clean_amount('send_amount') }} as send_amount_usd,
        upper(trim(send_currency)) as send_currency,
        {{ clean_amount('fx_rate', 6) }} as fx_rate,
        {{ clean_amount('reference_fx_rate', 6) }} as reference_fx_rate,
        {{ clean_amount('receive_amount') }} as receive_amount_local,
        upper(trim(receive_currency)) as receive_currency,
        {{ parse_timestamp('created_at') }} as created_at,
        _batch_id,
        _loaded_at
    from source
),

deduped as (
    {{ dedupe_latest('cleaned', 'receipt_id', '_loaded_at desc, _batch_id desc') }}
),

final as (
    select
        receipt_id,
        payment_id,
        user_id,
        beneficiary_id,
        send_amount_usd,
        send_currency,
        fx_rate,
        reference_fx_rate,
        receive_amount_local,
        receive_currency,
        created_at,
        _batch_id,
        _loaded_at
    from deduped
)

select * from final
