-- One row per remittance (receipt): payment lifecycle ⋈ receipt ⋈ final payout attempt.
-- Adds FX revenue (fx_revenue macro), chargeback loss and the end-to-end remittance status.
with

receipts as (
    select * from {{ ref('stg_felix_backend__receipts') }}
),

payments as (
    select * from {{ ref('int_payments__lifecycle') }}
),

attempts as (
    select * from {{ ref('int_disbursements__attempts_ranked') }}
),

attempt_summary as (
    select
        receipt_id,
        count(*) as n_attempts,
        count(*) filter (where is_failed) as n_failed_attempts,
        min(attempted_at) as first_attempt_at,
        max(_loaded_at) as _loaded_at
    from attempts
    group by receipt_id
),

final_attempts as (
    select
        receipt_id,
        beneficiary_country,
        provider_name,
        payout_method,
        final_status,
        completed_at
    from attempts
    where is_final_attempt
),

joined as (
    select
        receipts.receipt_id,
        receipts.payment_id,
        receipts.user_id,
        receipts.beneficiary_id,
        coalesce(
            final_attempts.beneficiary_country,
            case receipts.receive_currency
                {%- for country_code, corridor in var('corridors').items() %}
                    when '{{ corridor.currency }}' then '{{ country_code }}'
                {%- endfor %}
            end
        ) as destination_country,
        receipts.receive_currency,
        payments.payment_method,
        payments.payment_processor,
        payments.funding_institution,
        payments.funding_institution_type,
        receipts.send_amount_usd,
        payments.fee_amount_usd,
        payments.store_fee_amount_usd,
        receipts.fx_rate,
        receipts.reference_fx_rate,
        {{ fx_revenue('receipts.send_amount_usd', 'receipts.fx_rate', 'receipts.reference_fx_rate') }}
            as fx_revenue_usd,
        cast(
            case when payments.is_charged_back then receipts.send_amount_usd else 0 end as decimal(18, 2)
        ) as chargeback_loss_usd,
        receipts.receive_amount_local as payout_amount_local,
        coalesce(attempt_summary.n_attempts, 0) as n_attempts,
        coalesce(attempt_summary.n_failed_attempts, 0) as n_failed_attempts,
        final_attempts.provider_name as final_provider_name,
        final_attempts.payout_method as final_payout_method,
        final_attempts.final_status as final_attempt_status,
        payments.created_at as payment_created_at,
        payments.succeeded_at as payment_succeeded_at,
        receipts.created_at as receipt_created_at,
        attempt_summary.first_attempt_at,
        final_attempts.completed_at as delivered_at,
        payments.refunded_at,
        payments.chargeback_at,
        coalesce(payments.is_charged_back, false) as is_charged_back,
        coalesce(payments.is_refunded, false) as is_refunded,
        payments.payment_id is null as is_payment_missing,
        greatest(receipts._loaded_at, payments._loaded_at, attempt_summary._loaded_at) as _loaded_at
    from receipts
    left join payments on receipts.payment_id = payments.payment_id
    left join attempt_summary on receipts.receipt_id = attempt_summary.receipt_id
    left join final_attempts on receipts.receipt_id = final_attempts.receipt_id
),

final as (
    select
        receipt_id,
        payment_id,
        user_id,
        beneficiary_id,
        destination_country,
        receive_currency,
        payment_method,
        payment_processor,
        funding_institution,
        funding_institution_type,
        send_amount_usd,
        fee_amount_usd,
        store_fee_amount_usd,
        fx_rate,
        reference_fx_rate,
        fx_revenue_usd,
        chargeback_loss_usd,
        payout_amount_local,
        n_attempts,
        n_failed_attempts,
        final_provider_name,
        final_payout_method,
        final_attempt_status,
        payment_created_at,
        payment_succeeded_at,
        receipt_created_at,
        first_attempt_at,
        delivered_at,
        refunded_at,
        chargeback_at,
        date_diff('minute', receipt_created_at, delivered_at) as minutes_to_deliver,
        case
            when is_charged_back then 'charged_back'
            when is_refunded or final_attempt_status = 'failed' then 'failed_refunded'
            when final_attempt_status = 'completed' then 'delivered'
            else 'in_flight'
        end as remittance_status,
        coalesce(final_attempt_status = 'completed' and not is_charged_back and not is_refunded, false)
            as is_delivered,
        is_charged_back,
        is_refunded,
        is_payment_missing,
        _loaded_at
    from joined
)

select * from final
