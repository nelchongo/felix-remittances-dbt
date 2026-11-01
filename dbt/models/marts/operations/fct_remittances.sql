-- Accumulating snapshot, one row per remittance (receipt), updated as it moves through its milestones:
-- payment → receipt → first payout attempt → delivery (or refund / chargeback).
-- Incremental merge on receipt_id. Each run re-processes remittances issued in the last
-- var('chargeback_maturity_days') days and any remittance with a milestone since the last run.
with

remittances as (
    select
        *,
        greatest(
            receipt_created_at,
            coalesce(delivered_at, receipt_created_at),
            coalesce(refunded_at, receipt_created_at),
            coalesce(chargeback_at, receipt_created_at)
        ) as last_event_at
    from {{ ref('int_remittances__joined') }}
),

changed as (
    select candidates.* from remittances as candidates
    {% if is_incremental() %}
        where candidates.receipt_created_at is null
            or candidates.receipt_created_at
            >= (select max(current_table.receipt_created_at) from {{ this }} as current_table)
            - interval '{{ var("chargeback_maturity_days") }} days'
            or candidates.last_event_at > (select max(current_table.last_event_at) from {{ this }} as current_table)
    {% endif %}
),

users as (
    select * from {{ ref('dim_users') }}
),

beneficiaries as (
    select * from {{ ref('dim_beneficiaries') }}
),

payment_methods as (
    select * from {{ ref('dim_payment_methods') }}
),

payment_processors as (
    select * from {{ ref('dim_payment_processors') }}
),

funding_institutions as (
    select * from {{ ref('dim_funding_institutions') }}
),

payout_providers as (
    select * from {{ ref('dim_payout_providers') }}
),

corridors as (
    select * from {{ ref('dim_corridors') }}
),

final as (
    select
        changed.receipt_id,
        changed.payment_id,
        coalesce(users.user_sk, '-1') as user_sk,
        coalesce(beneficiaries.beneficiary_sk, '-1') as beneficiary_sk,
        coalesce(payment_methods.payment_method_sk, '-1') as payment_method_sk,
        coalesce(payment_processors.payment_processor_sk, '-1') as payment_processor_sk,
        coalesce(funding_institutions.funding_institution_sk, '-1') as funding_institution_sk,
        coalesce(payout_providers.payout_provider_sk, '-1') as payout_provider_sk,
        coalesce(corridors.corridor_sk, '-1') as corridor_sk,
        cast(strftime(changed.receipt_created_at, '%Y%m%d') as integer) as receipt_date_sk,
        cast(strftime(changed.delivered_at, '%Y%m%d') as integer) as delivered_date_sk,
        changed.user_id,
        changed.beneficiary_id,
        changed.destination_country,
        changed.receive_currency,
        changed.payment_method,
        changed.payment_processor,
        changed.funding_institution,
        changed.funding_institution_type,
        changed.final_provider_name,
        changed.final_payout_method,
        changed.remittance_status,
        changed.payment_created_at,
        changed.payment_succeeded_at,
        changed.receipt_created_at,
        changed.first_attempt_at,
        changed.delivered_at,
        changed.refunded_at,
        changed.chargeback_at,
        changed.last_event_at,
        changed.send_amount_usd,
        cast(coalesce(changed.fee_amount_usd, 0) as decimal(18, 2)) as fee_revenue_usd,
        cast(coalesce(changed.fx_revenue_usd, 0) as decimal(18, 4)) as fx_revenue_usd,
        changed.chargeback_loss_usd,
        changed.payout_amount_local,
        cast(changed.n_attempts as integer) as n_attempts,
        cast(changed.n_failed_attempts as integer) as n_failed_attempts,
        cast(changed.minutes_to_deliver as bigint) as minutes_to_deliver,
        changed.is_delivered,
        changed.remittance_status = 'in_flight' as is_in_flight,
        changed.remittance_status = 'failed_refunded' as is_failed_refunded,
        changed.is_charged_back
    from changed
    left join users
        on {{ scd2_point_in_time_join('users', 'changed.user_id', 'user_id', 'changed.receipt_created_at') }}
    left join beneficiaries
        on {{ scd2_point_in_time_join(
            'beneficiaries', 'changed.beneficiary_id', 'beneficiary_id', 'changed.receipt_created_at'
        ) }}
    left join payment_methods on changed.payment_method = payment_methods.payment_method
    left join payment_processors on changed.payment_processor = payment_processors.payment_processor
    left join funding_institutions on changed.funding_institution = funding_institutions.funding_institution
    left join payout_providers on changed.final_provider_name = payout_providers.provider_name
    left join corridors on changed.destination_country = corridors.country_code
)

select * from final
