-- Accumulating snapshot, one row per remittance (receipt), updated as it moves through its milestones:
-- payment → receipt → first payout attempt → delivery (or refund / chargeback).
-- Incremental merge on receipt_id. A run re-processes:
--   * remittances with a source row loaded since the last run (`_loaded_at` is load time, not business time:
--     receipt, payment events or payout attempts), so late or out-of-order milestones always reach their row;
--   * remittances issued in the last var('chargeback_maturity_days') days, so point-in-time user and
--     beneficiary versions catch up with late-arriving data.
-- A merge never deletes: when the loader removes rows from raw, run.py builds with --full-refresh.
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
        remittances.receipt_id,
        remittances.payment_id,
        coalesce(users.user_sk, '-1') as user_sk,
        coalesce(beneficiaries.beneficiary_sk, '-1') as beneficiary_sk,
        coalesce(payment_methods.payment_method_sk, '-1') as payment_method_sk,
        coalesce(payment_processors.payment_processor_sk, '-1') as payment_processor_sk,
        coalesce(funding_institutions.funding_institution_sk, '-1') as funding_institution_sk,
        coalesce(payout_providers.payout_provider_sk, '-1') as payout_provider_sk,
        coalesce(corridors.corridor_sk, '-1') as corridor_sk,
        cast(strftime(remittances.receipt_created_at, '%Y%m%d') as integer) as receipt_date_sk,
        cast(strftime(remittances.delivered_at, '%Y%m%d') as integer) as delivered_date_sk,
        remittances.user_id,
        remittances.beneficiary_id,
        remittances.destination_country,
        remittances.receive_currency,
        remittances.payment_method,
        remittances.payment_processor,
        remittances.funding_institution,
        remittances.funding_institution_type,
        remittances.final_provider_name,
        remittances.final_payout_method,
        remittances.remittance_status,
        remittances.payment_created_at,
        remittances.payment_succeeded_at,
        remittances.receipt_created_at,
        remittances.first_attempt_at,
        remittances.delivered_at,
        remittances.refunded_at,
        remittances.chargeback_at,
        remittances.last_event_at,
        remittances.send_amount_usd,
        cast(coalesce(remittances.fee_amount_usd, 0) as decimal(18, 2)) as fee_revenue_usd,
        cast(coalesce(remittances.fx_revenue_usd, 0) as decimal(18, 4)) as fx_revenue_usd,
        remittances.chargeback_loss_usd,
        remittances.payout_amount_local,
        cast(remittances.n_attempts as integer) as n_attempts,
        cast(remittances.n_failed_attempts as integer) as n_failed_attempts,
        cast(remittances.minutes_to_deliver as bigint) as minutes_to_deliver,
        remittances.is_delivered,
        remittances.remittance_status = 'in_flight' as is_in_flight,
        remittances.remittance_status = 'failed_refunded' as is_failed_refunded,
        remittances.is_charged_back,
        remittances._loaded_at
    from remittances
    left join users
        on {{ scd2_point_in_time_join('users', 'remittances.user_id', 'user_id', 'remittances.receipt_created_at') }}
    left join beneficiaries
        on {{ scd2_point_in_time_join(
            'beneficiaries', 'remittances.beneficiary_id', 'beneficiary_id', 'remittances.receipt_created_at'
        ) }}
    left join payment_methods on remittances.payment_method = payment_methods.payment_method
    left join payment_processors on remittances.payment_processor = payment_processors.payment_processor
    left join funding_institutions on remittances.funding_institution = funding_institutions.funding_institution
    left join payout_providers on remittances.final_provider_name = payout_providers.provider_name
    left join corridors on remittances.destination_country = corridors.country_code
)

select * from final
{% if is_incremental() %}
    where
        _loaded_at > (select max(current_table._loaded_at) from {{ this }} as current_table)
        or receipt_created_at is null
        or receipt_created_at >= (select max(current_table.receipt_created_at) from {{ this }} as current_table)
        - interval '{{ var("chargeback_maturity_days") }} days'
{% endif %}
