-- One row per payment: the status history pivoted into milestone timestamps and 0/1 flags.
-- Built from the event history, so a later chargeback or refund does not erase `succeeded_at`.
with

payment_events as (
    select * from {{ ref('stg_felix_backend__payment_events') }}
),

payments as (
    select * from {{ ref('stg_felix_backend__payments') }}
),

milestones as (
    select
        payment_id,
        min(updated_at) filter (where status = 'succeeded') as succeeded_at,
        min(updated_at) filter (where status = 'failed') as failed_at,
        min(updated_at) filter (where status = 'expired') as expired_at,
        min(updated_at) filter (where status = 'refunded') as refunded_at,
        min(updated_at) filter (where status = 'chargeback') as chargeback_at,
        max(failure_reason) filter (where status in ('failed', 'expired')) as decline_reason,
        max(failure_reason) filter (where status = 'chargeback') as chargeback_reason,
        max(failure_reason) filter (where status = 'refunded') as refund_reason
    from payment_events
    group by payment_id
),

joined as (
    select
        payments.payment_id,
        payments.user_id,
        payments.send_amount_usd,
        payments.fee_amount_usd,
        payments.store_fee_amount_usd,
        payments.payment_method,
        payments.payment_processor,
        payments.funding_institution,
        payments.funding_institution_type,
        payments.card_last4,
        payments.status as final_status,
        milestones.decline_reason,
        milestones.chargeback_reason,
        milestones.refund_reason,
        payments.created_at,
        milestones.succeeded_at,
        milestones.failed_at,
        milestones.expired_at,
        milestones.refunded_at,
        milestones.chargeback_at,
        payments.updated_at as last_updated_at,
        milestones.succeeded_at is not null as is_succeeded,
        milestones.failed_at is not null as is_failed,
        milestones.expired_at is not null as is_expired,
        milestones.refunded_at is not null as is_refunded,
        milestones.chargeback_at is not null as is_charged_back,
        payments.status = 'pending' as is_pending
    from payments
    inner join milestones on payments.payment_id = milestones.payment_id
),

final as (
    select
        payment_id,
        user_id,
        send_amount_usd,
        fee_amount_usd,
        store_fee_amount_usd,
        payment_method,
        payment_processor,
        funding_institution,
        funding_institution_type,
        card_last4,
        final_status,
        decline_reason,
        chargeback_reason,
        refund_reason,
        created_at,
        succeeded_at,
        failed_at,
        expired_at,
        refunded_at,
        chargeback_at,
        last_updated_at,
        date_diff('minute', created_at, succeeded_at) as minutes_to_pay,
        is_succeeded,
        is_failed,
        is_expired,
        is_refunded,
        is_charged_back,
        is_pending,
        coalesce(
            is_succeeded
            and row_number() over (
                partition by user_id, is_succeeded order by succeeded_at, payment_id
            ) = 1,
            false
        ) as is_first_transfer
    from joined
)

select * from final
